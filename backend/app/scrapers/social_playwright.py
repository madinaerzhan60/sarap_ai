from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.async_api import Browser, BrowserContext, Playwright, async_playwright

from app.scrapers.base import BaseScraper, ScraperBlocked
from app.scrapers.models import ScrapedItem
from app.scrapers.proxy_pool import ProxyPool
from app.scrapers.storage import SupabaseRawReviewStore


SOCIAL_SELECTORS = {
    "Instagram": ('article', '[role="dialog"] article'),
    "Threads": ('article', '[data-pressable-container="true"]'),
    "TikTok": ('[data-e2e="search-card-desc"]', '[data-e2e="comment-item"]'),
}


class SocialSessionScraper(BaseScraper):
    def __init__(self, source: str, storage: SupabaseRawReviewStore, proxy_pool: ProxyPool, storage_state: str | None = None) -> None:
        if source not in SOCIAL_SELECTORS:
            raise ValueError(f"Unsupported social source: {source}")
        self.source = source
        super().__init__(storage)
        self.proxy_pool = proxy_pool
        self.storage_state = storage_state
        self.playwright: Playwright | None = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None

    async def connect(self) -> None:
        proxy = await self.proxy_pool.next()
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=True, proxy=proxy.playwright() if proxy else None)
        state = self.storage_state if self.storage_state and Path(self.storage_state).is_file() else None
        self.context = await self.browser.new_context(storage_state=state, locale="ru-KZ", viewport={"width": 1280, "height": 900})

    async def scrape(self, query: str, limit: int = 50) -> list[ScrapedItem]:
        if not self.context:
            raise RuntimeError("connect() must run before scrape()")
        page = await self.context.new_page()
        await page.goto(query, wait_until="domcontentloaded", timeout=45_000)
        visible = (await page.locator("body").inner_text()).casefold()
        if any(value in visible for value in ("captcha", "verify you are human", "подтвердите, что вы не робот")):
            raise ScraperBlocked(f"{self.source} requested manual verification")
        max_scrolls = min(max(8, limit // 10), int(os.getenv("PLAYWRIGHT_MAX_SCROLLS", "200")))
        for _ in range(max_scrolls):
            await page.mouse.wheel(0, 1000)
            await asyncio.sleep(0.8)
        soup = BeautifulSoup(await page.content(), "html.parser")
        nodes = []
        for selector in SOCIAL_SELECTORS[self.source]:
            nodes = soup.select(selector)
            if nodes:
                break
        items: list[ScrapedItem] = []
        for index, node in enumerate(nodes[:limit]):
            text = node.get_text(" ", strip=True)
            if len(text) < 8:
                continue
            stable_hash = hashlib.sha256(f"{self.source}|{text}".encode()).hexdigest()[:24]
            items.append(ScrapedItem(source=self.source, author="Unknown", text_content=text, language="unknown", external_id=f"{self.source}-{index}-{stable_hash}", url=query, collected_by="playwright"))
        return items

    async def close(self) -> None:
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()


class InstagramScraper(SocialSessionScraper):
    def __init__(self, storage: SupabaseRawReviewStore, proxy_pool: ProxyPool, storage_state: str | None = None) -> None:
        super().__init__("Instagram", storage, proxy_pool, storage_state)


class ThreadsScraper(SocialSessionScraper):
    def __init__(self, storage: SupabaseRawReviewStore, proxy_pool: ProxyPool, storage_state: str | None = None) -> None:
        super().__init__("Threads", storage, proxy_pool, storage_state)


class TikTokScraper(SocialSessionScraper):
    def __init__(self, storage: SupabaseRawReviewStore, proxy_pool: ProxyPool, storage_state: str | None = None) -> None:
        super().__init__("TikTok", storage, proxy_pool, storage_state)
