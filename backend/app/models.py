from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, HttpUrl


class ConnectionType(StrEnum):
    official = "official"
    monitored = "monitored"
    provider = "provider"
    imported = "imported"


class CollectionMode(StrEnum):
    auto = "auto"
    api = "api"
    scraper = "scraper"


class MentionType(StrEnum):
    review = "review"
    social_post = "social_post"
    social_comment = "social_comment"
    news_article = "news_article"
    blog = "blog"
    forum = "forum"
    web_page = "web_page"
    video_comment = "video_comment"


class RawItem(BaseModel):
    source: str
    source_type: MentionType = MentionType.review
    external_id: str
    external_url: str | None = None
    author_name: str | None = None
    text: str = Field(min_length=1, max_length=30_000)
    rating: float | None = Field(default=None, ge=0, le=5)
    published_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class NormalizedMention(RawItem):
    id: UUID = Field(default_factory=uuid4)
    business_id: UUID
    collected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    language: str | None = None
    content_hash: str
    reviewed: bool = False


class Aspect(BaseModel):
    aspect: str
    sentiment: str


class AIAnalysis(BaseModel):
    language: str
    sentiment: str
    sentiment_score: float = Field(ge=-1, le=1)
    severity: str
    confidence: float = Field(ge=0, le=1)
    aspects: list[Aspect]
    escalated: bool = False


class RiskResult(BaseModel):
    score: int = Field(ge=0, le=100)
    level: str
    reasons: list[str]


class ProcessedMention(BaseModel):
    mention: NormalizedMention
    analysis: AIAnalysis
    risk: RiskResult
    alert_created: bool
    duplicate: bool = False


class SourceCreate(BaseModel):
    business_id: UUID
    source: str
    connection_type: ConnectionType
    collection_mode: CollectionMode = CollectionMode.auto
    source_url: HttpUrl | None = None


class DiscoveryRequest(BaseModel):
    business_id: UUID
    brand_name: str
    aliases: list[str] = Field(default_factory=list)
    city: str = "Almaty"
    country: str = "Kazakhstan"


class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str
    source: str
    published_at: datetime | None = None
    relevance: float = Field(ge=0, le=1)
