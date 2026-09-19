from __future__ import annotations

import asyncio
import hashlib
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from playwright.async_api import Browser, BrowserContext, Playwright, async_playwright

from app.scrapers.base import BaseScraper, ScraperBlocked
from app.scrapers.models import ScrapedItem
from app.scrapers.proxy_pool import ProxyPool
from app.scrapers.storage import SupabaseRawReviewStore


@dataclass(frozen=True)
class MapProfile:
    source: str
    card_selectors: tuple[str, ...]
    author_selectors: tuple[str, ...]
    text_selectors: tuple[str, ...]
    rating_selectors: tuple[str, ...]
    date_selectors: tuple[str, ...]


PROFILES = {
    "2gis": MapProfile("2GIS", ('[itemtype*="schema.org/Review"]', '[data-testid*="review"]', 'article'), ('[itemprop="author"]', '[class*="author"]'), ('[itemprop="reviewBody"]', '[class*="review"] p'), ('[itemprop="ratingValue"]', '[aria-label*="оцен"]'), ('[itemprop="datePublished"]', 'time')),
    "google_maps": MapProfile("Google Maps", ('div[data-review-id]', 'div.jftiEf'), ('.d4r55', '[class*="author"]'), ('.wiI7pd', '[data-expandable-section]'), ('span.kvMYJc', '[aria-label*="star"]'), ('.rsqaWe', 'time')),
    "yandex_maps": MapProfile("Yandex Maps", ('.business-review-view', '[class*="business-review"]'), ('.business-review-view__author', '[class*="author"]'), ('.business-review-view__body-text', '[class*="body-text"]'), ('[aria-label*="оценка"]', '[class*="rating"]'), ('.business-review-view__date', 'time')),
}


def _first_text(node: Any, selectors: tuple[str, ...]) -> str | None:
    for selector in selectors:
        found = node.select_one(selector)
        if found:
            value = found.get("content") or found.get("aria-label") or found.get_text(" ", strip=True)
            if value:
                return str(value).strip()
    return None


def _rating(value: str | None) -> float | None:
    if not value:
        return None
    match = re.search(r"([1-5](?:[.,]\d)?)", value)
    return float(match.group(1).replace(",", ".")) if match else None


def extract_map_items(
    html: str,
    profile: MapProfile,
    url: str,
    limit: int,
    collected_by: str,
) -> list[ScrapedItem]:
    soup = BeautifulSoup(html, "html.parser")
    cards: list[Any] = []
    for selector in profile.card_selectors:
        cards = soup.select(selector)
        if cards:
            break
    items: list[ScrapedItem] = []
    for index, card in enumerate(cards[:limit]):
        text = _first_text(card, profile.text_selectors)
        if not text or len(text) < 8:
            continue
        date_raw = _first_text(card, profile.date_selectors)
        published = None
        if date_raw:
            try:
                published = datetime.fromisoformat(date_raw.replace("Z", "+00:00"))
            except ValueError:
                published = None
        stable_hash = hashlib.sha256(f"{profile.source}|{text}".encode()).hexdigest()[:24]
        items.append(
            ScrapedItem(
                source=profile.source,
                author=_first_text(card, profile.author_selectors) or "Unknown",
                text_content=text,
                rating=_rating(_first_text(card, profile.rating_selectors)),
                published_at=published,
                language="unknown",
                external_id=card.get("data-review-id") or f"{profile.source}-{index}-{stable_hash}",
                url=url,
                metadata={"date_raw": date_raw},
                collected_by=collected_by,
            )
        )
    return items


class PlaywrightMapScraper(BaseScraper):
    def __init__(self, profile: MapProfile, storage: SupabaseRawReviewStore, proxy_pool: ProxyPool) -> None:
        self.profile = profile
        self.source = profile.source
        super().__init__(storage)
        self.proxy_pool = proxy_pool
        self.playwright: Playwright | None = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None

    async def connect(self) -> None:
        proxy = await self.proxy_pool.next()
        self.playwright = await async_playwright().start()
        executable = os.getenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE", "").strip()
        mac_chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        if not executable and Path(mac_chrome).is_file():
            executable = mac_chrome
        self.browser = await self.playwright.chromium.launch(headless=True, proxy=proxy.playwright() if proxy else None, executable_path=executable or None)
        self.context = await self.browser.new_context(locale="ru-KZ", timezone_id="Asia/Almaty", viewport={"width": 1280, "height": 900})

    async def scrape(self, query: str, limit: int = 50) -> list[ScrapedItem]:
        if not self.context:
            raise RuntimeError("connect() must run before scrape()")
        page = await self.context.new_page()
        await page.goto(query, wait_until="domcontentloaded", timeout=45_000)
        if self.profile.source == "2GIS":
            requested = re.search(r"/firm/(\d+)", query)
            if not requested or not re.search(rf"/firm/{re.escape(requested.group(1))}(?:/|$)", page.url):
                raise ScraperBlocked("2GIS redirected away from the requested company card")
        body_text = (await page.locator("body").inner_text()).casefold()
        blocked = ("captcha", "капча", "подтвердите, что вы не робот", "подозрительную активность", "access denied")
        if "captcha.2gis." in page.url or any(marker in body_text for marker in blocked):
            raise ScraperBlocked(f"{self.source} requested manual verification")
        previous_height = 0
        max_scrolls = min(max(12, limit // 10), int(os.getenv("PLAYWRIGHT_MAX_SCROLLS", "200")))
        for _ in range(max_scrolls):
            await page.mouse.wheel(0, 1200)
            await asyncio.sleep(0.8)
            height = await page.evaluate("document.body.scrollHeight")
            if height == previous_height:
                break
            previous_height = height
        return extract_map_items(await page.content(), self.profile, query, limit, "playwright")

    async def close(self) -> None:
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()


class TwoGisScraper(PlaywrightMapScraper):
    def __init__(self, storage: SupabaseRawReviewStore, proxy_pool: ProxyPool) -> None:
        super().__init__(PROFILES["2gis"], storage, proxy_pool)


class GoogleMapsScraper(PlaywrightMapScraper):
    def __init__(self, storage: SupabaseRawReviewStore, proxy_pool: ProxyPool) -> None:
        super().__init__(PROFILES["google_maps"], storage, proxy_pool)


class YandexMapsScraper(PlaywrightMapScraper):
    def __init__(self, storage: SupabaseRawReviewStore, proxy_pool: ProxyPool) -> None:
        super().__init__(PROFILES["yandex_maps"], storage, proxy_pool)
