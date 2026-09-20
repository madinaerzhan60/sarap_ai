from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import random
import re
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from bs4 import BeautifulSoup

from app.scrapers.base import BaseScraper, ScraperEmptyConfirmed
from app.scrapers.browser_runtime import BrowserRuntimeError
from app.scrapers.maps_playwright import PROFILES, extract_map_items
from app.scrapers.models import ScrapedItem
from app.scrapers.storage import SupabaseRawReviewStore


class ProviderError(RuntimeError):
    """A provider failed in a way that allows the next fallback to run."""


class ProviderNotConfigured(ProviderError):
    pass


class EmptyResult(ProviderError):
    pass


class ConfirmedEmptyResult(ProviderError):
    """The source loaded successfully and explicitly contains zero items."""


class TransientProviderError(ProviderError):
    pass


class StorageWriteError(RuntimeError):
    pass


def env_enabled(name: str, default: bool = False) -> bool:
    return os.getenv(name, "true" if default else "false").strip().casefold() in {"1", "true", "yes", "on"}


def paid_provider_enabled(provider: str) -> bool:
    """Paid collectors require both the global and provider-specific opt-in."""
    return env_enabled("ENABLE_PAID_FALLBACKS") and env_enabled(f"ENABLE_{provider.upper()}")


class ProviderUsageGuard:
    """Small runtime circuit breaker; durable counters are also persisted by production workers."""

    _state: dict[tuple[str, str, str], dict[str, Any]] = {}

    @classmethod
    def reset(cls) -> None:
        cls._state.clear()

    @classmethod
    def allow(cls, provider: str, business_id: str) -> tuple[bool, str | None]:
        today = datetime.now(timezone.utc).date().isoformat()
        key = (provider, business_id or "global", today)
        row = cls._state.setdefault(key, {"calls": 0, "failures": 0, "disabled_until": None})
        disabled_until = row.get("disabled_until")
        if disabled_until and disabled_until > datetime.now(timezone.utc):
            return False, "circuit breaker cooldown"
        maximum = int(os.getenv(f"{provider.upper()}_MAX_CALLS_PER_BUSINESS_PER_DAY", "2"))
        if row["calls"] >= maximum:
            return False, "daily limit reached"
        row["calls"] += 1
        return True, None

    @classmethod
    def record(cls, provider: str, business_id: str, success: bool) -> None:
        today = datetime.now(timezone.utc).date().isoformat()
        row = cls._state.setdefault((provider, business_id or "global", today), {"calls": 0, "failures": 0, "disabled_until": None})
        if success:
            row["failures"] = 0
            return
        row["failures"] += 1
        if row["failures"] >= int(os.getenv("PROVIDER_FAILURE_THRESHOLD", "3")):
            row["disabled_until"] = datetime.now(timezone.utc) + timedelta(minutes=int(os.getenv("PROVIDER_COOLDOWN_MINUTES", "60")))


class CollectorProvider(ABC):
    name: str
    platform: str

    @property
    def configured(self) -> bool:
        return True

    @abstractmethod
    async def collect(self, target_url: str, limit: int) -> list[ScrapedItem]:
        raise NotImplementedError


def _datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _first(mapping: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        value: Any = mapping
        for part in key.split("."):
            if not isinstance(value, dict) or part not in value:
                value = None
                break
            value = value[part]
        if value not in (None, "", []):
            return value
    return default


def _list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    if isinstance(value, dict):
        return [row for row in value.values() if isinstance(row, dict)]
    return []


def normalize_api_item(row: dict[str, Any], platform: str, target_url: str, collected_by: str) -> ScrapedItem | None:
    content = _first(row, "text", "review_text", "reviewText", "comment", "caption", "content.text", "content")
    if isinstance(content, dict):
        content = _first(content, "text", "value")
    if not isinstance(content, str) or len(content.strip()) < 2:
        return None
    author = _first(row, "author_name", "authorName", "username", "ownerUsername", "user.username", "author.username", "author.name", default="Unknown")
    rating = _first(row, "rating", "stars", "reviewRating.ratingValue")
    try:
        parsed_rating = float(rating) if rating is not None else None
        if parsed_rating is not None and not 0 <= parsed_rating <= 5:
            parsed_rating = None
    except (TypeError, ValueError):
        parsed_rating = None
    external_id = str(_first(row, "id", "comment_id", "commentId", "review_id", "reviewId", default="")) or None
    published = _datetime(_first(row, "created_at", "createdAt", "published_at", "publishedAt", "publishedTime", "dateCreated", "date", "timestamp"))
    metadata = {
        "likes_count": _first(row, "likes_count", "likesCount", "likes", "likeCount", "comment_like_count", "engagement.likes", default=0),
        "business_reply": _first(row, "replyText", "business_reply"),
        "raw_provider_fields": sorted(row.keys()),
    }
    source_names = {"2gis": "2GIS", "instagram": "Instagram", "youtube": "YouTube"}
    return ScrapedItem(
        source=source_names.get(platform, platform),
        author=str(author or "Unknown"),
        text_content=content,
        rating=parsed_rating,
        published_at=published,
        external_id=external_id,
        url=target_url,
        metadata=metadata,
        collected_by=collected_by,
    )


class PlaywrightProvider(CollectorProvider):
    name = "playwright"

    def __init__(self, platform: str, scraper_factory: Callable[[], BaseScraper]) -> None:
        self.platform = platform
        self.scraper_factory = scraper_factory

    async def collect(self, target_url: str, limit: int) -> list[ScrapedItem]:
        scraper = self.scraper_factory()
        try:
            await scraper.connect()
            try:
                return scraper.clean_data(await scraper.scrape(target_url, limit))
            except ScraperEmptyConfirmed as exc:
                raise ConfirmedEmptyResult(str(exc)) from exc
        except BrowserRuntimeError as exc:
            raise ProviderError(f"{exc.code}: {exc}") from exc
        finally:
            await scraper.close()


class SociaVaultProvider(CollectorProvider):
    name = "sociavault"
    platform = "instagram"
    endpoint = "https://api.sociavault.com/v1/scrape/instagram/comments"

    def __init__(self, api_key: str | None) -> None:
        self.api_key = (api_key or "").strip()

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def collect(self, target_url: str, limit: int) -> list[ScrapedItem]:
        if not self.configured:
            raise ProviderNotConfigured("SOCIAVAULT_API_KEY is empty")
        results: list[ScrapedItem] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        async with httpx.AsyncClient(timeout=45) as client:
            while len(results) < limit:
                params = {"url": target_url}
                if cursor:
                    params["cursor"] = cursor
                response = await client.get(self.endpoint, headers={"X-API-Key": self.api_key}, params=params)
                _raise_for_provider_status(response, self.name)
                payload = response.json()
                data = payload.get("data", {}) if isinstance(payload, dict) else {}
                for row in _list(data.get("comments")):
                    item = normalize_api_item(row, self.platform, target_url, self.name)
                    if item:
                        results.append(item)
                        if len(results) >= limit:
                            break
                next_cursor = data.get("cursor") if isinstance(data, dict) else None
                if not next_cursor or next_cursor in seen_cursors:
                    break
                seen_cursors.add(next_cursor)
                cursor = next_cursor
        return results


def instagram_profile_handle(target_url: str) -> str | None:
    """Return a public profile handle, excluding Instagram system routes."""
    from urllib.parse import urlparse

    path_parts = [part for part in urlparse(target_url).path.split("/") if part]
    if len(path_parts) != 1:
        return None
    handle = path_parts[0].lstrip("@").strip()
    reserved = {
        "about", "accounts", "developer", "direct", "directory", "emails",
        "explore", "legal", "oauth", "privacy", "reels", "stories", "web",
    }
    if not handle or handle.casefold() in reserved or not re.fullmatch(r"[A-Za-z0-9._]+", handle):
        return None
    return handle


def instagram_post_urls(payload: Any) -> list[str]:
    """Extract canonical post/reel URLs from the profile-posts response."""
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    rows = _list(_first(data, "items", "posts") if isinstance(data, dict) else None)
    urls: list[str] = []
    for row in rows:
        direct_url = _first(row, "url", "permalink", "post_url", "postUrl")
        shortcode = _first(row, "shortcode", "code", "node.shortcode")
        product_type = str(_first(row, "product_type", "productType", "media_type", default="")).casefold()
        direct_match = re.search(r"instagram\.com/(?:[^/]+/)?(p|reel)/([^/?#]+)", direct_url) if isinstance(direct_url, str) else None
        if direct_match:
            url = f"https://www.instagram.com/{direct_match.group(1)}/{direct_match.group(2)}/"
        elif shortcode:
            route = "reel" if "reel" in product_type or product_type == "clips" else "p"
            url = f"https://www.instagram.com/{route}/{shortcode}/"
        else:
            continue
        if url not in urls:
            urls.append(url)
    return urls


class SociaVaultInstagramProfileProvider(CollectorProvider):
    """Resolve a public profile to recent posts, then collect their comments."""

    name = "sociavault"
    platform = "instagram"
    posts_endpoint = "https://api.sociavault.com/v1/scrape/instagram/posts"

    def __init__(self, api_key: str | None) -> None:
        self.api_key = (api_key or "").strip()

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def collect(self, target_url: str, limit: int) -> list[ScrapedItem]:
        if not self.configured:
            raise ProviderNotConfigured(
                "Instagram profile scanning needs SOCIAVAULT_API_KEY or an official Instagram account connection"
            )
        handle = instagram_profile_handle(target_url)
        if not handle:
            raise ProviderError("sociavault: invalid Instagram profile URL")
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.get(
                self.posts_endpoint,
                headers={"X-API-Key": self.api_key},
                params={"handle": handle},
            )
            _raise_for_provider_status(response, self.name)
            post_urls = instagram_post_urls(response.json())
        if not post_urls:
            return []

        maximum_posts = max(1, int(os.getenv("INSTAGRAM_PROFILE_POST_LIMIT", "5")))
        profile_limit = min(limit, max(1, int(os.getenv("INSTAGRAM_PROFILE_COMMENT_LIMIT", "75"))))
        per_post_limit = max(1, int(os.getenv("INSTAGRAM_COMMENTS_PER_POST_LIMIT", "15")))
        comments_provider = SociaVaultProvider(self.api_key)
        results: list[ScrapedItem] = []
        failures: list[str] = []
        for post_url in post_urls[:maximum_posts]:
            try:
                comments = await comments_provider.collect(
                    post_url,
                    min(per_post_limit, profile_limit - len(results)),
                )
                for item in comments:
                    item.metadata["profile_handle"] = handle
                    item.metadata["post_url"] = post_url
                results.extend(comments)
            except ProviderError as exc:
                failures.append(str(exc))
            if len(results) >= profile_limit:
                break
        if not results and failures:
            raise ProviderError(f"sociavault: profile posts found, but comments could not be collected ({failures[0]})")
        return results[:profile_limit]


class SocialCrawlProvider(CollectorProvider):
    name = "socialcrawl"
    platform = "instagram"
    endpoint = "https://www.socialcrawl.dev/v1/instagram/post/comments"

    def __init__(self, api_key: str | None) -> None:
        self.api_key = (api_key or "").strip()

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def collect(self, target_url: str, limit: int) -> list[ScrapedItem]:
        if not self.configured:
            raise ProviderNotConfigured("SOCIALCRAWL_API_KEY is empty")
        results: list[ScrapedItem] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        async with httpx.AsyncClient(timeout=60) as client:
            while len(results) < limit:
                params = {"url": target_url, "sort": "recent"}
                if cursor:
                    params["cursor"] = cursor
                response = await client.get(self.endpoint, headers={"x-api-key": self.api_key}, params=params)
                _raise_for_provider_status(response, self.name)
                payload = response.json()
                data = payload.get("data", {}) if isinstance(payload, dict) else {}
                rows = _list(data.get("items") if isinstance(data, dict) else None)
                if not rows and isinstance(data, dict):
                    rows = _list(data.get("comments"))
                for row in rows:
                    item = normalize_api_item(row, self.platform, target_url, self.name)
                    if item:
                        results.append(item)
                        if len(results) >= limit:
                            break
                next_cursor = _first(data, "next_cursor", "cursor") if isinstance(data, dict) else None
                if not next_cursor or next_cursor in seen_cursors:
                    break
                seen_cursors.add(str(next_cursor))
                cursor = str(next_cursor)
        return results


class SociaVaultYouTubeProvider(CollectorProvider):
    name = "sociavault"
    platform = "youtube"
    endpoint = "https://api.sociavault.com/v1/scrape/youtube/video/comments"

    def __init__(self, api_key: str | None) -> None:
        self.api_key = (api_key or "").strip()

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def collect(self, target_url: str, limit: int) -> list[ScrapedItem]:
        if not self.configured:
            raise ProviderNotConfigured("SOCIAVAULT_API_KEY is empty")
        results: list[ScrapedItem] = []
        continuation: str | None = None
        seen_tokens: set[str] = set()
        async with httpx.AsyncClient(timeout=60) as client:
            while len(results) < limit:
                params = {"url": target_url, "order": "newest"}
                if continuation:
                    params["continuationToken"] = continuation
                response = await client.get(self.endpoint, headers={"X-API-Key": self.api_key}, params=params)
                _raise_for_provider_status(response, self.name)
                payload = response.json()
                data = payload.get("data", {}) if isinstance(payload, dict) else {}
                for row in _list(data.get("comments")):
                    item = normalize_api_item(row, self.platform, target_url, self.name)
                    if item:
                        item.metadata["is_reply"] = bool(row.get("replyLevel"))
                        results.append(item)
                        if len(results) >= limit:
                            break
                next_token = data.get("continuationToken") if isinstance(data, dict) else None
                if not next_token or next_token in seen_tokens:
                    break
                seen_tokens.add(str(next_token))
                continuation = str(next_token)
        return results


class ScrapflyProvider(CollectorProvider):
    name = "scrapfly"
    endpoint = "https://api.scrapfly.io/scrape"

    def __init__(self, platform: str, api_key: str | None) -> None:
        self.platform = platform
        self.api_key = (api_key or "").strip()

    @property
    def configured(self) -> bool:
        return paid_provider_enabled("scrapfly") and bool(self.api_key)

    async def collect(self, target_url: str, limit: int) -> list[ScrapedItem]:
        if not self.configured:
            raise ProviderNotConfigured("SCRAPFLY_API_KEY is empty")
        params = {
            "key": self.api_key,
            "url": target_url,
            "render_js": "true",
            "auto_scroll": "true",
            "country": os.getenv("SCRAPFLY_COUNTRY", "kz"),
        }
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.get(self.endpoint, params=params)
        _raise_for_provider_status(response, self.name)
        payload = response.json()
        if self.platform == "2gis":
            requested = re.search(r"/firm/(\d+)", target_url)
            final_url = str(_first(payload, "result.url", "url", default=target_url))
            if not requested or not re.search(rf"/firm/{re.escape(requested.group(1))}(?:/|$)", final_url):
                raise ProviderError("scrapfly: 2GIS redirected away from the requested firm")
        html = _first(payload, "result.content", "content", default="")
        if not isinstance(html, str):
            return []
        if self.platform in PROFILES:
            return extract_map_items(html, PROFILES[self.platform], target_url, limit, self.name)
        return _instagram_html_items(html, target_url, limit, self.name)


class ApifyProvider(CollectorProvider):
    name = "apify"

    def __init__(self, platform: str, token: str | None, actor_id: str | None, input_json: str | None = None) -> None:
        self.platform = platform
        self.token = (token or "").strip()
        self.actor_id = (actor_id or "").strip()
        self.input_json = (input_json or "").strip()

    @property
    def configured(self) -> bool:
        return paid_provider_enabled("apify") and bool(self.token and self.actor_id)

    async def collect(self, target_url: str, limit: int) -> list[ScrapedItem]:
        if not self.configured:
            raise ProviderNotConfigured(f"APIFY_API_TOKEN or APIFY_{self.platform.upper()}_ACTOR_ID is empty")
        maximum = min(limit, int(os.getenv("APIFY_MAX_ITEMS_PER_RUN", "1000")))
        if self.input_json:
            run_input = json.loads(self.input_json)
        elif self.platform == "2gis" and self.actor_id == "getascraper/2gis-reviews-scraper":
            firm_match = re.search(r"/firm/(\d+)", target_url)
            if not firm_match:
                raise ProviderError("apify: no /firm/<id> in URL")
            run_input = {
                "firmIds": [firm_match.group(1)],
                "urls": [],
                "maxItemsPerFirm": maximum,
                "withTextOnly": True,
                "includeRawData": False,
            }
        elif self.platform == "instagram":
            run_input = {"directUrls": [target_url], "resultsLimit": maximum}
        else:
            run_input = {"startUrls": [{"url": target_url}], "maxItems": maximum}
        if self.platform == "2gis":
            firm_match = re.search(r"/firm/(\d+)", target_url)
            if not firm_match:
                raise ProviderError("apify: no /firm/<id> in URL")
            run_input["firmIds"] = [firm_match.group(1)]
            run_input["urls"] = []
        actor_path = self.actor_id.replace("/", "~")
        endpoint = f"https://api.apify.com/v2/acts/{actor_path}/run-sync-get-dataset-items"
        timeout_seconds = int(os.getenv("APIFY_RUN_TIMEOUT_SECONDS", "300"))
        async with httpx.AsyncClient(timeout=timeout_seconds + 30) as client:
            response = await client.post(
                endpoint,
                params={"token": self.token, "timeout": timeout_seconds, "clean": "true"},
                json=run_input,
            )
        _raise_for_provider_status(response, self.name)
        rows = response.json()
        if not isinstance(rows, list):
            raise ProviderError("apify: actor returned an unexpected response")
        results: list[ScrapedItem] = []
        requested_firm = re.search(r"/firm/(\d+)", target_url) if self.platform == "2gis" else None
        for row in rows[:maximum]:
            if not isinstance(row, dict):
                continue
            if requested_firm:
                row_firm = str(_first(row, "firmId", "firm_id", "firm.id", default=""))
                if row_firm and row_firm != requested_firm.group(1):
                    continue
            item = normalize_api_item(row, self.platform, target_url, self.name)
            if item:
                results.append(item)
        return results


def _raise_for_provider_status(response: httpx.Response, provider: str) -> None:
    if response.status_code in {401, 403}:
        raise ProviderError(f"{provider}: API key is invalid, expired, or denied ({response.status_code})")
    if response.status_code in {402, 429}:
        raise ProviderError(f"{provider}: credits or rate limit reached ({response.status_code})")
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        error = TransientProviderError if response.status_code >= 500 else ProviderError
        raise error(f"{provider}: HTTP {response.status_code}") from exc


def _instagram_html_items(html: str, target_url: str, limit: int, collected_by: str) -> list[ScrapedItem]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[ScrapedItem] = []
    for node in soup.select("article ul li"):
        text = node.get_text(" ", strip=True)
        if len(text) < 2:
            continue
        author_node = node.select_one('a[href^="/"]')
        author = author_node.get_text(" ", strip=True) if author_node else "Unknown"
        identity = hashlib.sha256(f"{author}|{text}".encode()).hexdigest()
        results.append(ScrapedItem(source="Instagram", author=author, text_content=text, external_id=identity, url=target_url, collected_by=collected_by))
        if len(results) >= limit:
            break
    return results


class FallbackPipeline:
    def __init__(self, platform: str, providers: list[CollectorProvider], storage: SupabaseRawReviewStore | None = None, business_id: str = "global") -> None:
        self.platform = platform
        self.providers = providers
        self.storage = storage
        self.business_id = business_id
        self.log = logging.getLogger(f"sarap.fallback.{platform}")

    async def collect_items(
        self,
        target_url: str,
        limit: int = 10_000,
    ) -> tuple[list[ScrapedItem], str | None, list[dict[str, str]]]:
        if limit < 1:
            raise ValueError("limit must be positive")
        failures: list[dict[str, str]] = []
        attempts = max(1, int(os.getenv("FALLBACK_RETRY_ATTEMPTS", "2")))
        for provider in self.providers:
            if not provider.configured:
                failures.append({"provider": provider.name, "error": "disabled or not configured"})
                continue
            is_paid = provider.name in {"apify", "scrapfly"}
            if is_paid:
                allowed, reason = ProviderUsageGuard.allow(provider.name, self.business_id)
                if not allowed:
                    failures.append({"provider": provider.name, "error": reason or "usage limit"})
                    continue
            for retry_number in range(attempts):
                try:
                    items = await provider.collect(target_url, limit)
                    unique = {item.stable_id(): item for item in items}
                    if not unique:
                        raise EmptyResult(f"{provider.name}: empty result")
                    normalized = list(unique.values())[:limit]
                    if is_paid:
                        ProviderUsageGuard.record(provider.name, self.business_id, True)
                    return normalized, provider.name, failures
                except ConfirmedEmptyResult:
                    # A verified zero is a successful collection. Calling a paid
                    # fallback here would spend money for the same empty result.
                    return [], provider.name, failures
                except ProviderNotConfigured as exc:
                    failures.append({"provider": provider.name, "error": str(exc)})
                    break
                except (httpx.TransportError, TimeoutError, TransientProviderError) as exc:
                    self.log.warning("%s attempt %s failed: %s", provider.name, retry_number + 1, exc)
                    if retry_number + 1 < attempts:
                        await asyncio.sleep(2**retry_number + random.uniform(0, 0.25))
                    else:
                        failures.append({"provider": provider.name, "error": str(exc)})
                except (EmptyResult, ProviderError) as exc:
                    failures.append({"provider": provider.name, "error": str(exc)})
                    if is_paid:
                        ProviderUsageGuard.record(provider.name, self.business_id, False)
                    break
                except StorageWriteError:
                    raise
                except Exception as exc:
                    self.log.warning("%s attempt %s failed: %s", provider.name, retry_number + 1, exc)
                    if retry_number + 1 < attempts:
                        await asyncio.sleep(2**retry_number + random.uniform(0, 0.25))
                    else:
                        failures.append({"provider": provider.name, "error": str(exc)})
        return [], None, failures

    async def collect_data(self, target_url: str, limit: int = 10_000) -> dict[str, Any]:
        items, provider_name, failures = await self.collect_items(target_url, limit)
        if not items or not provider_name:
            return {"platform": self.platform, "status": "error", "collected": 0, "saved": 0, "fallbacks": failures}
        if self.storage is None:
            raise StorageWriteError("Supabase storage is required for collect_data()")
        # A database failure is not a provider failure. Do not pay the next API
        # to fetch the same records again.
        try:
            saved = await self.storage.save(
                items,
                batch_size=int(os.getenv("COLLECTOR_BATCH_SIZE", "250")),
            )
        except Exception as exc:
            raise StorageWriteError(f"Supabase batch save failed: {exc}") from exc
        return {
            "platform": self.platform,
            "status": "ok",
            "collected_by": provider_name,
            "collected": len(items),
            "saved": saved,
            "fallbacks": failures,
        }
