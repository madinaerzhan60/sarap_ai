from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
import os

import httpx

from app.models import SearchResult


class SearchProvider(ABC):
    @abstractmethod
    async def search(self, query: str, language: str, country: str, date_range: str) -> list[SearchResult]: ...


class DemoSearchProvider(SearchProvider):
    async def search(self, query: str, language: str = "all", country: str = "KZ", date_range: str = "7d") -> list[SearchResult]:
        return [SearchResult(title="Coffee Boom opens a new location in Astana", url="https://example.com/demo-news", snippet="The Kazakhstan café chain is expanding its bakery menu.", source="Demo News", published_at=datetime.now(timezone.utc), relevance=.94)]


class GdeltSearchProvider(SearchProvider):
    """Free news/media discovery. GDELT does not require an API key."""

    async def search(self, query: str, language: str = "all", country: str = "KZ", date_range: str = "7d") -> list[SearchResult]:
        endpoint = os.getenv("GDELT_API_BASE", "https://api.gdeltproject.org/api/v2/doc/doc")
        timespan = {"7d": "1week", "30d": "1month", "90d": "3months"}.get(date_range, date_range)
        params = {
            "query": query,
            "mode": "artlist",
            "format": "json",
            "maxrecords": 50,
            "sort": "datedesc",
            "timespan": timespan,
        }
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            response = await client.get(endpoint, params=params)
            response.raise_for_status()
        results: list[SearchResult] = []
        for article in response.json().get("articles", []):
            title = article.get("title") or "Untitled article"
            published_at = _gdelt_date(article.get("seendate"))
            results.append(
                SearchResult(
                    title=title,
                    url=article["url"],
                    snippet=title,
                    source=article.get("domain") or "GDELT",
                    published_at=published_at,
                    relevance=.85,
                )
            )
        return results


class FreeSearchProvider(SearchProvider):
    """Keyless discovery layer. Add RSS and monitored pages as connectors."""

    def __init__(self) -> None:
        self.providers: list[SearchProvider] = [GdeltSearchProvider()]

    async def search(self, query: str, language: str = "all", country: str = "KZ", date_range: str = "7d") -> list[SearchResult]:
        results: list[SearchResult] = []
        for provider in self.providers:
            try:
                results.extend(await provider.search(query, language, country, date_range))
            except (httpx.HTTPError, KeyError, ValueError):
                continue
        return list({item.url: item for item in results}.values())


def _gdelt_date(value: str | None) -> datetime | None:
    if not value:
        return None
    for format_ in ("%Y%m%dT%H%M%SZ", "%Y%m%d%H%M%S"):
        try:
            return datetime.strptime(value, format_).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def fan_out(brand: str, aliases: list[str], city: str) -> list[str]:
    names = [brand, *aliases]
    intents = ["отзывы", "жалоба", "сервис", city, "Kazakhstan", "новости", "қауіп"]
    return list(dict.fromkeys(f'"{name}" {intent}' for name in names for intent in intents))
