from __future__ import annotations

import logging
import os
import re
import inspect
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.connectors.base import BaseConnector
from app.models import MentionType, RawItem

logger = logging.getLogger("sarap.collectors")


class SourceType(StrEnum):
    TWO_GIS = "2gis"
    GOOGLE_MAPS = "google_maps"
    GOOGLE_BUSINESS = "google_business"
    YANDEX_MAPS = "yandex_maps"
    INSTAGRAM = "instagram"
    THREADS = "threads"
    LINKEDIN = "linkedin"
    FACEBOOK = "facebook"
    REDDIT = "reddit"
    YOUTUBE = "youtube"
    TELEGRAM = "telegram"
    WEBSITE = "website"
    RSS = "rss"


ALIASES = {
    "2gis": SourceType.TWO_GIS, "2gis maps": SourceType.TWO_GIS,
    "google": SourceType.GOOGLE_BUSINESS, "google business": SourceType.GOOGLE_BUSINESS,
    "google_business": SourceType.GOOGLE_BUSINESS, "google maps": SourceType.GOOGLE_MAPS,
    "google_maps": SourceType.GOOGLE_MAPS,
    "yandex": SourceType.YANDEX_MAPS, "yandex maps": SourceType.YANDEX_MAPS,
    "yandex_maps": SourceType.YANDEX_MAPS,
    "instagram": SourceType.INSTAGRAM, "instagram comments": SourceType.INSTAGRAM,
    "threads": SourceType.THREADS, "linkedin": SourceType.LINKEDIN,
    "facebook": SourceType.FACEBOOK, "reddit": SourceType.REDDIT, "youtube": SourceType.YOUTUBE,
    "youtube channel": SourceType.YOUTUBE, "telegram": SourceType.TELEGRAM,
    "website": SourceType.WEBSITE, "web": SourceType.WEBSITE,
    "website / rss": SourceType.WEBSITE, "rss": SourceType.RSS,
    "feed": SourceType.RSS, "atom": SourceType.RSS,
}


def normalize_source_type(value: str, source_url: str | None = None) -> SourceType:
    key = re.sub(r"\s+", " ", value.casefold().strip())
    result = ALIASES.get(key)
    if not result:
        raise ValueError(f"Unsupported source type: {value}")
    url = (source_url or "").casefold()
    if result == SourceType.GOOGLE_BUSINESS and "google." in url and "/maps" in url:
        return SourceType.GOOGLE_MAPS
    if result == SourceType.WEBSITE and (url.endswith(".rss") or url.endswith(".xml") or "/feed" in url):
        return SourceType.RSS
    return result


@dataclass
class CollectionResult:
    success: bool
    source: str
    provider: str
    items: list[RawItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def collected_count(self) -> int:
        return len(self.items)


def _error_code(message: str) -> str:
    lowered = message.casefold()
    if "collector_unavailable" in lowered or "requires collector_worker_url" in lowered:
        return "collector_unavailable"
    for code in ("chromium_not_installed", "browser_launch_failed", "navigation_timeout", "parser_failed"):
        if code in lowered:
            return code
    if "oauth" in lowered or "token has expired" in lowered or "access token" in lowered:
        return "auth_required"
    if "playwright" in lowered or "chromium" in lowered or "browser" in lowered or "executable doesn't exist" in lowered:
        return "browser_launch_failed"
    if "setup_required" in lowered or "not configured" in lowered or "is empty" in lowered or "requires" in lowered and "api" in lowered:
        return "setup_required"
    if "429" in lowered or "rate limit" in lowered or "quota" in lowered:
        return "rate_limited"
    if "captcha" in lowered or "verification" in lowered:
        return "captcha"
    if "blocked" in lowered or "robots.txt" in lowered:
        return "blocked"
    if "empty result" in lowered or "no public" in lowered or "no structured" in lowered or "selectors found no items" in lowered:
        return "parser_failed"
    return "collection_failed"


def _friendly_collection_error(source: str, code: str) -> str:
    label = {"2gis":"2GIS", "yandex_maps":"Yandex Maps", "google_maps":"Google Maps", "telegram":"Telegram", "instagram":"Instagram"}.get(source, source.replace("_", " ").title())
    if code == "setup_required":
        return f"{label} monitoring is not configured yet."
    if code == "collector_unavailable":
        return f"{label} collector is unavailable. Configure COLLECTOR_WORKER_URL."
    if code == "auth_required":
        return f"Reconnect {label} in Source settings."
    if code in {"captcha", "blocked"}:
        return f"{label} blocked automatic collection. Please try again later."
    if code == "rate_limited":
        return f"{label} is temporarily rate limited. Please try again later."
    return f"{label} could not be reached. Please try again later."


def get_provider_status() -> dict[str, str]:
    variables = {
        "sociavault": "SOCIAVAULT_API_KEY", "socialcrawl": "SOCIALCRAWL_API_KEY",
        "apify": "APIFY_API_TOKEN", "scrapfly": "SCRAPFLY_API_KEY",
        "youtube_api": "YOUTUBE_API_KEY", "telegram_api_id": "TELEGRAM_API_ID",
        "telegram_api_hash": "TELEGRAM_API_HASH",
    }
    return {name: "configured" if os.getenv(variable, "").strip() else "missing_credentials" for name, variable in variables.items()}


class CollectorRegistry:
    def resolve(self, source: dict[str, Any], credentials: dict[str, Any] | None = None) -> tuple[SourceType, BaseConnector]:
        from typing import cast

        from app.connectors.feeds import MonitoredPageConnector, RssConnector
        from app.connectors.reviews import (
            ConnectorUnavailable, GoogleBusinessReviewsConnector, InstagramFallbackConnector,
            InstagramGraphCommentsConnector, MapFallbackConnector, ModularScraperConnector,
            TwoGisPlaywrightConnector, YouTubePublicConnector,
        )
        from app.scrapers.proxy_pool import ProxyPool
        from app.scrapers.social_playwright import ThreadsScraper
        from app.scrapers.storage import SupabaseRawReviewStore
        from app.scrapers.telegram_api import TelegramScraper

        business_id = str(source.get("business_id") or "global")
        raw_url = source.get("source_url")
        page_url = str(raw_url) if raw_url else ""
        source_type = normalize_source_type(str(source["source"]), page_url)
        mode = str(source.get("collection_mode", "auto"))
        use_worker = bool(os.getenv("COLLECTOR_WORKER_URL", "").strip())
        if source_type == SourceType.TWO_GIS:
            provider_key = os.getenv("TWOGIS_PROVIDER", "direct").strip().lower()
            from app.connectors.reviews import TwoGisPlaywrightConnector, MapFallbackConnector

            if provider_key == "brightdata":
                from app.connectors.brightdata_twogis import BrightDataTwoGisConnector
                return source_type, BrightDataTwoGisConnector(page_url, business_id)

            if provider_key == "zenrows":
                from app.connectors.zenrows_twogis import ZenRowsTwoGisConnector
                return source_type, ZenRowsTwoGisConnector(page_url, business_id)

            if provider_key == "direct":
                return source_type, TwoGisPlaywrightConnector(page_url, business_id)

            return source_type, MapFallbackConnector("2gis", page_url, business_id)

        if source_type == SourceType.YANDEX_MAPS:
            provider_key = os.getenv("YANDEX_PROVIDER", "direct").strip().lower()
            from app.connectors.reviews import MapFallbackConnector

            if provider_key == "direct":
                return source_type, MapFallbackConnector(
                    "yandex_maps",
                    page_url,
                    business_id,
                )

            return source_type, MapFallbackConnector(
                "yandex_maps",
                page_url,
                business_id,
            )
        if source_type in {SourceType.GOOGLE_BUSINESS, SourceType.GOOGLE_MAPS}:
            if credentials and mode in {"auto", "api"}:
                return SourceType.GOOGLE_BUSINESS, GoogleBusinessReviewsConnector(
                    credentials.get("access_token", ""), credentials.get("account_id", ""), credentials.get("location_id", "")
                )
            if use_worker and page_url:
                from app.connectors.worker import ExternalWorkerConnector
                return SourceType.GOOGLE_MAPS, ExternalWorkerConnector("google_maps", page_url)
            if mode == "api":
                raise ConnectorUnavailable("Google Business OAuth is not connected for this workspace source")
            if not page_url:
                raise ConnectorUnavailable("Google Maps fallback requires a public Google Maps business URL")
            return SourceType.GOOGLE_MAPS, MapFallbackConnector("google_maps", page_url, business_id)
        if source_type == SourceType.INSTAGRAM:
            # Provider selection via environment variable (default to direct)
            env_var = f"{source_type.value.upper().replace('_', '')}_PROVIDER"
            provider_key = os.getenv(env_var, "direct").strip().lower()
            from app.connectors import InstagramApifyConnector
            from app.connectors.reviews import (
                InstagramFallbackConnector,
                InstagramGraphCommentsConnector,
            )
            from app.connectors.discovery import PublicDiscoveryConnector
            if provider_key == "direct":
                # If official credentials are supplied, use the official Graph connector
                if credentials and credentials.get("access_token"):
                    return source_type, InstagramGraphCommentsConnector(
                        credentials.get("access_token"),
                        credentials.get("instagram_user_id"),
                        credentials.get("media_id"),
                    )
                # Direct public discovery
                return source_type, PublicDiscoveryConnector("instagram", page_url)
            elif provider_key == "apify":
                return source_type, InstagramApifyConnector(page_url, business_id)
            else:
                # Use fallback pipeline (Playwright, SociaVault, SocialCrawl, Apify)
                return source_type, InstagramFallbackConnector(page_url, business_id)
        if source_type == SourceType.YOUTUBE:
            if not page_url:
                raise ConnectorUnavailable("YouTube collection requires a public video or channel URL")
            return source_type, YouTubePublicConnector(page_url)
        if source_type == SourceType.THREADS:
            if not page_url:
                raise ConnectorUnavailable("Threads collection requires a public profile or post URL")
            proxies = ProxyPool([value for value in os.getenv("WEBSHARE_PROXY_URLS", "").split(",") if value.strip()])
            connector = ModularScraperConnector("threads", page_url, lambda: ThreadsScraper(cast(SupabaseRawReviewStore, None), proxies, os.getenv("THREADS_STORAGE_STATE")), MentionType.social_post)
            return source_type, connector
        if source_type == SourceType.FACEBOOK:
            # Provider selection via environment variable (default to direct)
            env_var = f"{source_type.value.upper()}_PROVIDER"
            provider_key = os.getenv(env_var, "direct").strip().lower()
            from app.connectors import FacebookApifyConnector
            from app.connectors.discovery import PublicDiscoveryConnector
            if provider_key == "direct":
                return source_type, PublicDiscoveryConnector("facebook", page_url)
            elif provider_key == "apify":
                return source_type, FacebookApifyConnector(page_url, business_id)
            else:
                raise ConnectorUnavailable(f"Unsupported Facebook provider: {provider_key}")
        elif source_type in {SourceType.LINKEDIN, SourceType.REDDIT}:
            if not page_url:
                raise ConnectorUnavailable(f"{source_type.value} monitoring requires a public page URL")
            from app.connectors.discovery import PublicDiscoveryConnector
            return source_type, PublicDiscoveryConnector(source_type.value, page_url)
            if not page_url:
                raise ConnectorUnavailable(f"{source_type.value} monitoring requires a public page URL")
            from app.connectors.discovery import PublicDiscoveryConnector
            return source_type, PublicDiscoveryConnector(source_type.value, page_url)
        if source_type == SourceType.TELEGRAM:
            api_id, api_hash = os.getenv("TELEGRAM_API_ID", ""), os.getenv("TELEGRAM_API_HASH", "")
            missing = [name for name, value in (("TELEGRAM_API_ID", api_id), ("TELEGRAM_API_HASH", api_hash)) if not value]
            if missing:
                raise ConnectorUnavailable("setup_required: Telegram monitoring is not configured yet")
            if not page_url:
                raise ConnectorUnavailable("Telegram monitoring requires a public t.me channel URL")
            connector = ModularScraperConnector("telegram", page_url, lambda: TelegramScraper(cast(SupabaseRawReviewStore, None), int(api_id), api_hash, os.getenv("TELEGRAM_SESSION", "sarap-telegram")), MentionType.social_post)
            return source_type, connector
        if not page_url:
            raise ConnectorUnavailable(f"{source_type.value} collection requires a public URL")
        if source_type == SourceType.RSS:
            return source_type, RssConnector(page_url, "rss")
        return source_type, MonitoredPageConnector(page_url, "website")

    async def collect(self, source: dict[str, Any], credentials: dict[str, Any] | None = None, last_seen_item_id: str | None = None, *, backfill: bool = False) -> CollectionResult:
        try:
            source_type, connector = self.resolve(source, credentials)
            if "backfill" in inspect.signature(connector.fetch_latest).parameters:
                items = await connector.fetch_latest(last_seen_item_id, backfill=backfill)
            else:
                items = await connector.fetch_latest(last_seen_item_id)
            provider = str(getattr(connector, "collection_method", connector.connection_type.value))
            confirmed_empty = bool(getattr(connector, "confirmed_empty", False))
            metadata = dict(getattr(connector, "last_collection_metadata", {}) or {})
            metadata["mode"] = "backfill" if backfill else "incremental"
            logger.info("source=%s provider=%s status=success mode=%s collected=%d", source_type.value, provider, metadata["mode"], len(items))
            return CollectionResult(True, source_type.value, provider, items, metadata=metadata)
        except Exception as exc:
            source_name = str(source.get("source", "unknown"))
            try:
                normalized = normalize_source_type(source_name, str(source.get("source_url") or "")).value
            except ValueError:
                normalized = source_name.casefold().strip()
            code = _error_code(str(exc))
            logger.warning("source=%s provider=registry status=failed reason=%s error_type=%s detail=%s", normalized, code, type(exc).__name__, exc)
            return CollectionResult(False, normalized, "registry", error_code=code, error_message=_friendly_collection_error(normalized, code))


collector_registry = CollectorRegistry()
