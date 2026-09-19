from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
import os
import re
from xml.etree import ElementTree
import asyncio

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


class GoogleNewsRssProvider(SearchProvider):
    """Keyless Google News RSS search for regional brand mentions."""

    async def search(self, query: str, language: str = "all", country: str = "KZ", date_range: str = "7d") -> list[SearchResult]:
        endpoint = os.getenv("GOOGLE_NEWS_RSS_BASE", "https://news.google.com/rss/search")
        params = {"q": f"{query} when:{date_range}", "hl": "ru", "gl": country, "ceid": f"{country}:ru"}
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            response = await client.get(endpoint, params=params)
            response.raise_for_status()
        root = ElementTree.fromstring(response.content)
        results: list[SearchResult] = []
        for item in root.findall("./channel/item")[:30]:
            title = (item.findtext("title") or "Untitled article").strip()
            url = (item.findtext("link") or "").strip()
            if not url:
                continue
            description = unescape(item.findtext("description") or title)
            snippet = re.sub(r"<[^>]+>", " ", description)
            snippet = re.sub(r"\s+", " ", snippet).strip()
            source_node = item.find("source")
            source = (source_node.text if source_node is not None else None) or "Google News"
            published_at = None
            if item.findtext("pubDate"):
                try:
                    published_at = parsedate_to_datetime(item.findtext("pubDate"))
                except (TypeError, ValueError):
                    pass
            results.append(SearchResult(title=title, url=url, snippet=snippet, source=source, published_at=published_at, relevance=.82))
        return results


class FreeSearchProvider(SearchProvider):
    """Keyless discovery layer. Add RSS and monitored pages as connectors."""

    def __init__(self) -> None:
        self.providers: list[SearchProvider] = [GoogleNewsRssProvider(), GdeltSearchProvider()]

    async def search(self, query: str, language: str = "all", country: str = "KZ", date_range: str = "7d") -> list[SearchResult]:
        async def run(provider: SearchProvider) -> list[SearchResult]:
            try:
                return await asyncio.wait_for(provider.search(query, language, country, date_range), timeout=8)
            except (asyncio.TimeoutError, httpx.HTTPError, KeyError, ValueError, ElementTree.ParseError):
                return []

        calls = [run(provider) for provider in self.providers]
        batches = await asyncio.gather(*calls, return_exceptions=True)
        results: list[SearchResult] = []
        for batch in batches:
            if not isinstance(batch, BaseException):
                results.extend(batch)
        return list({item.url: item for item in results}.values())

    async def search_many(self, queries: list[str], *, country: str = "KZ", date_range: str = "30d") -> tuple[list[SearchResult], list[dict[str, object]]]:
        """Search news queries concurrently while respecting GDELT's low request rate."""
        jobs: list[tuple[str, str, SearchProvider]] = [
            ("google_news", query, GoogleNewsRssProvider()) for query in queries[:3]
        ]
        if queries:
            jobs.append(("gdelt", queries[0], GdeltSearchProvider()))

        async def run(name: str, query: str, provider: SearchProvider) -> tuple[str, list[SearchResult], str | None]:
            try:
                rows = await asyncio.wait_for(provider.search(query, "all", country, date_range), timeout=10)
                return name, rows, None
            except asyncio.TimeoutError:
                return name, [], "timeout"
            except httpx.HTTPStatusError as exc:
                return name, [], f"HTTP {exc.response.status_code}"
            except (httpx.HTTPError, KeyError, ValueError, ElementTree.ParseError) as exc:
                return name, [], type(exc).__name__

        batches = await asyncio.gather(*(run(*job) for job in jobs))
        results: list[SearchResult] = []
        grouped: dict[str, dict[str, object]] = {}
        for name, rows, error in batches:
            status = grouped.setdefault(name, {"provider": name, "status": "ok", "results": 0})
            status["results"] = int(status["results"]) + len(rows)
            if error:
                status["status"] = "limited" if error in {"timeout", "HTTP 429"} else "error"
                status["detail"] = error
            results.extend(rows)
        return list({item.url: item for item in results}.values()), list(grouped.values())


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
