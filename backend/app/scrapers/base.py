from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from collections.abc import Iterable

from app.scrapers.models import ScrapedItem, detect_language
from app.scrapers.storage import SupabaseRawReviewStore


class ScraperEmptyConfirmed(RuntimeError):
    """The page loaded and explicitly confirmed that it has no items."""


class ScraperBlocked(RuntimeError):
    """The source returned a login wall, CAPTCHA, robots denial or access block."""


class BaseScraper(ABC):
    source: str

    def __init__(self, storage: SupabaseRawReviewStore) -> None:
        self.storage = storage
        self.log = logging.getLogger(f"sarap.scraper.{self.source}")

    @abstractmethod
    async def connect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def scrape(self, query: str, limit: int = 50) -> list[ScrapedItem]:
        raise NotImplementedError

    def clean_data(self, items: Iterable[ScrapedItem]) -> list[ScrapedItem]:
        unique: dict[str, ScrapedItem] = {}
        for item in items:
            text = re.sub(r"\s+", " ", item.text_content).strip()
            if len(text) < 2:
                continue
            language = detect_language(text) if item.language == "unknown" else item.language
            cleaned = item.model_copy(update={"text_content": text, "language": language})
            unique[cleaned.stable_id()] = cleaned
        return list(unique.values())

    async def save_to_supabase(self, items: Iterable[ScrapedItem]) -> int:
        return await self.storage.save(self.clean_data(items))

    async def close(self) -> None:
        return None

    async def run(self, query: str, limit: int = 50) -> tuple[int, int]:
        await self.connect()
        try:
            items = self.clean_data(await self.scrape(query, limit))
            return len(items), await self.save_to_supabase(items)
        finally:
            await self.close()
