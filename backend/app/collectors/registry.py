from __future__ import annotations

import logging
import os
import re
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
    "threads": SourceType.THREADS, "youtube": SourceType.YOUTUBE,
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

    @property
    def collected_count(self) -> int:
        return len(self.items)


def _error_code(message: str) -> str:
    lowered = message.casefold()
    for code in ("chromium_not_installed", "browser_launch_failed", "navigation_timeout", "parser_failed"):
        if code in lowered:
            return code
    if "oauth" in lowered or "token has expired" in lowered or "access token" in lowered:
        return "auth_required"
    if "playwright" in lowered or "chromium" in lowered or "browser" in lowered or "executable doesn't exist" in lowered:
        return "browser_launch_failed"
    if "not configured" in lowered or "is empty" in lowered or "requires" in lowered and "api" in lowered:
        return "not_configured"
    if "429" in lowered or "rate limit" in lowered or "quota" in lowered:
        return "rate_limited"
    if "captcha" in lowered or "verification" in lowered:
        return "captcha"
    if "blocked" in lowered or "robots.txt" in lowered:
        return "blocked"
    if "empty result" in lowered or "no public" in lowered or "no structured" in lowered or "selectors found no items" in lowered:
        return "parser_failed"
    return "collection_failed"


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

        raw_url = source.get("source_url")
        page_url = str(raw_url) if raw_url else ""
        source_type = normalize_source_type(str(source["source"]), page_url)
        mode = str(source.get("collection_mode", "auto"))
        if source_type == SourceType.TWO_GIS:
            if mode == "auto" and os.getenv("ENABLE_DEMO_CONNECTORS", "false").lower() == "true":
                from app.connectors.demo import DemoTwoGisConnector
                return source_type, DemoTwoGisConnector()
            if not page_url:
                raise ConnectorUnavailable("2GIS collection requires the business page URL")
            return source_type, TwoGisPlaywrightConnector(page_url)
        if source_type in {SourceType.GOOGLE_BUSINESS, SourceType.GOOGLE_MAPS}:
            if credentials and mode in {"auto", "api"}:
                return SourceType.GOOGLE_BUSINESS, GoogleBusinessReviewsConnector(
                    credentials.get("access_token", ""), credentials.get("account_id", ""), credentials.get("location_id", "")
                )
            if mode == "api":
                raise ConnectorUnavailable("Google Business OAuth is not connected for this workspace source")
            if not page_url:
                raise ConnectorUnavailable("Google Maps fallback requires a public Google Maps business URL")
            return SourceType.GOOGLE_MAPS, MapFallbackConnector("google_maps", page_url)
        if source_type == SourceType.YANDEX_MAPS:
            if not page_url:
                raise ConnectorUnavailable("Yandex Maps collection requires the exact business page URL")
            return source_type, MapFallbackConnector("yandex_maps", page_url)
        if source_type == SourceType.INSTAGRAM:
            if credentials and mode in {"auto", "api"}:
                return source_type, InstagramGraphCommentsConnector(
                    credentials.get("access_token", ""), credentials.get("instagram_user_id"), credentials.get("media_id")
                )
            if mode == "api":
                raise ConnectorUnavailable("Instagram OAuth is not connected for this workspace source")
            if not page_url:
                raise ConnectorUnavailable("Instagram collection requires a public profile, post or reel URL")
            return source_type, InstagramFallbackConnector(page_url)
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
        if source_type == SourceType.TELEGRAM:
            api_id, api_hash = os.getenv("TELEGRAM_API_ID", ""), os.getenv("TELEGRAM_API_HASH", "")
            missing = [name for name, value in (("TELEGRAM_API_ID", api_id), ("TELEGRAM_API_HASH", api_hash)) if not value]
            if missing:
                raise ConnectorUnavailable(f"Telegram integration is not configured: missing {' / '.join(missing)}")
            if not page_url:
                raise ConnectorUnavailable("Telegram monitoring requires a public t.me channel URL")
            connector = ModularScraperConnector("telegram", page_url, lambda: TelegramScraper(cast(SupabaseRawReviewStore, None), int(api_id), api_hash, os.getenv("TELEGRAM_SESSION", "sarap-telegram")), MentionType.social_post)
            return source_type, connector
        if not page_url:
            raise ConnectorUnavailable(f"{source_type.value} collection requires a public URL")
        if source_type == SourceType.RSS:
            return source_type, RssConnector(page_url, "rss")
        return source_type, MonitoredPageConnector(page_url, "website")

    async def collect(self, source: dict[str, Any], credentials: dict[str, Any] | None = None, last_seen_item_id: str | None = None) -> CollectionResult:
        try:
            source_type, connector = self.resolve(source, credentials)
            items = await connector.fetch_latest(last_seen_item_id)
            provider = str(getattr(connector, "collection_method", connector.connection_type.value))
            confirmed_empty = bool(getattr(connector, "confirmed_empty", False))
            if not items and not confirmed_empty and source_type not in {SourceType.RSS, SourceType.WEBSITE, SourceType.GOOGLE_BUSINESS, SourceType.TELEGRAM}:
                message = f"{source_type.value} collector returned no structured items; the parser or provider may be unavailable"
                logger.warning("source=%s provider=%s status=failed reason=parser_failed", source_type.value, provider)
                return CollectionResult(False, source_type.value, provider, error_code="parser_failed", error_message=message)
            logger.info("source=%s provider=%s status=success collected=%d", source_type.value, provider, len(items))
            return CollectionResult(True, source_type.value, provider, items)
        except Exception as exc:
            source_name = str(source.get("source", "unknown"))
            try:
                normalized = normalize_source_type(source_name, str(source.get("source_url") or "")).value
            except ValueError:
                normalized = source_name.casefold().strip()
            code = _error_code(str(exc))
            logger.warning("source=%s provider=registry status=failed reason=%s error_type=%s", normalized, code, type(exc).__name__)
            return CollectionResult(False, normalized, "registry", error_code=code, error_message=str(exc))


collector_registry = CollectorRegistry()
