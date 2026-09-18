from __future__ import annotations

import asyncio
import hashlib
from urllib.parse import urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup

from app.scrapers.base import BaseScraper
from app.scrapers.models import ScrapedItem
from app.scrapers.proxy_pool import ProxyPool
from app.scrapers.retry import with_retry
from app.scrapers.storage import SupabaseRawReviewStore


class NewsForumCrawler(BaseScraper):
    def __init__(self, source: str, storage: SupabaseRawReviewStore, proxy_pool: ProxyPool, max_concurrency: int = 4) -> None:
        if source not in {"News", "Forum_Blog"}:
            raise ValueError(f"Unsupported web source: {source}")
        self.source = source
        super().__init__(storage)
        self.proxy_pool = proxy_pool
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.session: aiohttp.ClientSession | None = None

    async def connect(self) -> None:
        timeout = aiohttp.ClientTimeout(total=25)
        self.session = aiohttp.ClientSession(timeout=timeout, headers={"User-Agent": "SARAPBot/1.0 (+https://sarap.ai/bot)"})

    async def _fetch(self, url: str) -> str:
        if not self.session:
            raise RuntimeError("connect() must run before scrape()")
        async def request() -> str:
            proxy = await self.proxy_pool.next()
            async with self.semaphore:
                async with self.session.get(url, proxy=proxy.aiohttp_url() if proxy else None, allow_redirects=True) as response:
                    response.raise_for_status()
                    return await response.text(errors="replace")

        return await with_retry(request, retry_for=(aiohttp.ClientError, asyncio.TimeoutError))

    async def scrape(self, query: str, limit: int = 50) -> list[ScrapedItem]:
        html = await self._fetch(query)
        soup = BeautifulSoup(html, "html.parser")
        for node in soup(["script", "style", "nav", "footer", "aside", "form", "noscript"]):
            node.decompose()
        article = soup.select_one("article") or soup.select_one("main") or soup.body
        if not article:
            return []
        title_node = soup.select_one("h1") or soup.select_one("title")
        paragraphs = [node.get_text(" ", strip=True) for node in article.select("p, blockquote, [itemprop='articleBody']")]
        paragraphs = [text for text in paragraphs if len(text) >= 40][:limit]
        host = urlparse(query).hostname or "web"
        return [ScrapedItem(source=self.source, author=host, text_content=text, language="unknown", external_id=f"{host}-{index}-{hashlib.sha256(text.encode()).hexdigest()[:24]}", url=query, metadata={"title": title_node.get_text(" ", strip=True) if title_node else None, "canonical": urljoin(query, soup.select_one('link[rel="canonical"]')['href']) if soup.select_one('link[rel="canonical"]') else query}) for index, text in enumerate(paragraphs)]

    async def close(self) -> None:
        if self.session:
            await self.session.close()
