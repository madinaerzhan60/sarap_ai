from __future__ import annotations

from typing import Any

from app.scrapers.base import BaseScraper
from app.scrapers.models import ScrapedItem
from app.scrapers.storage import SupabaseRawReviewStore


class TelegramScraper(BaseScraper):
    source = "Telegram"

    def __init__(self, storage: SupabaseRawReviewStore, api_id: int, api_hash: str, session: str) -> None:
        super().__init__(storage)
        try:
            from telethon import TelegramClient
        except ImportError as exc:
            raise RuntimeError("Install backend requirements to enable the Telegram collector") from exc
        self.client: Any = TelegramClient(session, api_id, api_hash)

    async def connect(self) -> None:
        await self.client.connect()
        if not await self.client.is_user_authorized():
            raise RuntimeError("Telegram session is not authorized; create it locally before deployment")

    async def scrape(self, query: str, limit: int = 50) -> list[ScrapedItem]:
        entity = await self.client.get_entity(query)
        items: list[ScrapedItem] = []
        async for message in self.client.iter_messages(entity, limit=limit):
            text = (message.message or "").strip()
            if not text:
                continue
            sender = await message.get_sender()
            author = getattr(sender, "username", None) or getattr(sender, "first_name", None) or "Unknown"
            items.append(ScrapedItem(source=self.source, author=str(author), text_content=text, published_at=message.date, language="unknown", external_id=f"{entity.id}-{message.id}", url=f"https://t.me/{getattr(entity, 'username', '')}/{message.id}", metadata={"views": message.views, "forwards": message.forwards}))
        return items

    async def close(self) -> None:
        await self.client.disconnect()
