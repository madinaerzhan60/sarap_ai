from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, field_validator


KAZAKH_LETTERS = set("ӘәҒғҚқҢңӨөҰұҮүҺһІі")
RUSSIAN_MARKERS = {"но", "и", "или", "очень", "плохо", "хорошо", "доставка", "сервис", "кофе", "кассир", "медленно", "медленная"}


def detect_language(text: str) -> str:
    kazakh = sum(char in KAZAKH_LETTERS for char in text)
    cyrillic = len(re.findall(r"[А-Яа-яЁё]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    if kazakh:
        words = set(re.findall(r"[А-Яа-яЁёӘәҒғҚқҢңӨөҰұҮүҺһІі]+", text.casefold()))
        return "mixed" if words & RUSSIAN_MARKERS else "kk"
    if cyrillic:
        return "mixed" if latin > cyrillic // 2 else "ru"
    return "en" if latin else "unknown"


class ScrapedItem(BaseModel):
    source: str
    author: str = "Unknown"
    text_content: str = Field(min_length=1, max_length=30_000)
    rating: float | None = Field(default=None, ge=0, le=5)
    published_at: datetime | None = None
    language: str = "unknown"
    external_id: str | None = None
    url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    collected_by: str = "unknown"

    @field_validator("text_content", "author")
    @classmethod
    def normalize_space(cls, value: str) -> str:
        return re.sub(r"\s+", " ", value).strip()

    def stable_id(self) -> str:
        if self.external_id:
            return self.external_id
        payload = f"{self.source}|{self.author}|{self.published_at}|{self.text_content}".casefold()
        return hashlib.sha256(payload.encode()).hexdigest()

    def database_row(self, business_id: str) -> dict[str, Any]:
        return {
            "business_id": business_id,
            "source": self.source,
            "external_id": self.stable_id(),
            "author": self.author,
            "text_content": self.text_content,
            "rating": self.rating,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "language": self.language,
            "url": self.url,
            "metadata": self.metadata,
            "collected_by": self.collected_by,
        }
