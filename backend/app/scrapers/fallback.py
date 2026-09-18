from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import random
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime
from typing import Any

import httpx
from bs4 import BeautifulSoup

from app.scrapers.base import BaseScraper
from app.scrapers.maps_playwright import PROFILES, extract_map_items
from app.scrapers.models import ScrapedItem
from app.scrapers.storage import SupabaseRawReviewStore


class ProviderError(RuntimeError):
    """A provider failed in a way that allows the next fallback to run."""


class ProviderNotConfigured(ProviderError):
    pass


class EmptyResult(ProviderError):
    pass


class TransientProviderError(ProviderError):
    pass


class StorageWriteError(RuntimeError):
    pass


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
    published = _datetime(_first(row, "created_at", "createdAt", "published_at", "publishedAt", "date", "timestamp"))
    metadata = {
        "likes_count": _first(row, "likes_count", "likes", "likeCount", "engagement.likes", default=0),
        "raw_provider_fields": sorted(row.keys()),
    }
    return ScrapedItem(
        source="2GIS" if platform == "2gis" else "Instagram",
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
        await scraper.connect()
        try:
            return scraper.clean_data(await scraper.scrape(target_url, limit))
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


class ScrapflyProvider(CollectorProvider):
    name = "scrapfly"
    endpoint = "https://api.scrapfly.io/scrape"

    def __init__(self, platform: str, api_key: str | None) -> None:
        self.platform = platform
        self.api_key = (api_key or "").strip()

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

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
        html = _first(payload, "result.content", "content", default="")
        if not isinstance(html, str):
            return []
        if self.platform == "2gis":
            return extract_map_items(html, PROFILES["2gis"], target_url, limit, self.name)
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
        return bool(self.token and self.actor_id)

    async def collect(self, target_url: str, limit: int) -> list[ScrapedItem]:
        if not self.configured:
            raise ProviderNotConfigured(f"APIFY_API_TOKEN or APIFY_{self.platform.upper()}_ACTOR_ID is empty")
        from apify_client import ApifyClientAsync

        maximum = min(limit, int(os.getenv("APIFY_MAX_ITEMS_PER_RUN", "1000")))
        if self.input_json:
            run_input = json.loads(self.input_json)
        elif self.platform == "instagram":
            run_input = {"directUrls": [target_url], "resultsLimit": maximum}
        else:
            run_input = {"startUrls": [{"url": target_url}], "maxItems": maximum}
        client = ApifyClientAsync(self.token)
        run = await client.actor(self.actor_id).call(run_input=run_input)
        if not run:
            return []
        dataset_id = getattr(run, "default_dataset_id", None)
        if not dataset_id and isinstance(run, dict):
            dataset_id = run.get("defaultDatasetId")
        if not dataset_id:
            raise ProviderError("apify: actor run returned no default dataset")
        page = await client.dataset(dataset_id).list_items(limit=maximum, clean=True)
        results: list[ScrapedItem] = []
        for row in page.items:
            item = normalize_api_item(row, self.platform, target_url, self.name)
            if item:
                results.append(item)
        return results


def _raise_for_provider_status(response: httpx.Response, provider: str) -> None:
    if response.status_code in {401, 403}:
        raise ProviderError(f"{provider}: authentication or access denied ({response.status_code})")
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
    def __init__(self, platform: str, providers: list[CollectorProvider], storage: SupabaseRawReviewStore | None = None) -> None:
        self.platform = platform
        self.providers = providers
        self.storage = storage
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
                failures.append({"provider": provider.name, "error": "not configured"})
                continue
            for retry_number in range(attempts):
                try:
                    items = await provider.collect(target_url, limit)
                    unique = {item.stable_id(): item for item in items}
                    if not unique:
                        raise EmptyResult(f"{provider.name}: empty result")
                    normalized = list(unique.values())[:limit]
                    return normalized, provider.name, failures
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
