from __future__ import annotations

from datetime import date, datetime, timezone
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, HttpUrl, SecretStr


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


class ContentType(StrEnum):
    review = "review"
    comment = "comment"
    question = "question"
    post = "post"
    news = "news"
    other = "other"


class AuthorType(StrEnum):
    customer = "customer"
    employee = "employee"
    company = "company"
    unknown = "unknown"


class ReplyStatus(StrEnum):
    none = "none"
    draft = "draft"
    answered = "answered"


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
    dedupe_key: str = ""
    is_duplicate: bool = False
    duplicate_group_id: str | None = None
    canonical_mention_id: str | None = None
    reviewed: bool = False
    content_type: ContentType = ContentType.review
    author_type: AuthorType = AuthorType.unknown
    include_in_analysis: bool = True
    reply_draft: str | None = None
    reply_generated_at: datetime | None = None
    reply_status: ReplyStatus = ReplyStatus.none


class Aspect(BaseModel):
    aspect: str
    sentiment: str


class AIAnalysis(BaseModel):
    language: str
    sentiment: str
    summary: str = ""
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


class SourceUpdate(BaseModel):
    source_url: HttpUrl | None = None
    collection_mode: CollectionMode = CollectionMode.auto


class SourceOAuthCredential(BaseModel):
    access_token: SecretStr
    refresh_token: SecretStr | None = None
    expires_at: datetime | None = None
    account_id: str | None = Field(default=None, max_length=500)
    location_id: str | None = Field(default=None, max_length=500)
    instagram_user_id: str | None = Field(default=None, max_length=500)
    media_id: str | None = Field(default=None, max_length=500)


class ImportFieldMapping(BaseModel):
    text: str | None = None
    author: str | None = None
    rating: str | None = None
    published_at: str | None = None
    external_id: str | None = None
    source_url: str | None = None
    source: str | None = None
    content_type: str | None = None


class SourceImportRequest(BaseModel):
    business_id: UUID
    ingestion_method: str = Field(pattern="^(csv|json|manual)$")
    platform: str = "Other"
    use_source_from_file: bool = False
    display_name: str | None = Field(default=None, max_length=200)
    filename: str | None = Field(default=None, max_length=240)
    csv_content: str | None = Field(default=None, max_length=2_000_000)
    json_content: str | None = Field(default=None, max_length=2_000_000)
    manual_item: dict[str, Any] | None = None
    mapping: ImportFieldMapping = Field(default_factory=ImportFieldMapping)
    default_content_type: str | None = None


class SourceImportResult(BaseModel):
    source: dict[str, Any] | None = None
    total_read: int
    inserted: int
    duplicates: int
    invalid: int
    failed: int
    source_used: str
    items: list[ProcessedMention] = Field(default_factory=list)


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


class ReviewPlatform(StrEnum):
    two_gis = "2GIS"
    google_maps = "Google Maps"
    yandex_maps = "Yandex Maps"
    instagram = "Instagram"
    threads = "Threads"
    tiktok = "TikTok"
    telegram = "Telegram"
    youtube = "YouTube"
    news = "News"
    forum_blog = "Forum_Blog"


class ReviewMetaInfo(BaseModel):
    is_reply: bool = False
    business_reply: str | None = None
    extra_details: str | None = None


class ExtractedReview(BaseModel):
    source_platform: ReviewPlatform
    author_name: str = "Unknown"
    rating: float | None = Field(default=None, ge=1, le=5)
    estimated_sentiment: Literal["positive", "negative", "neutral"]
    language: Literal["ru", "kk", "en", "mixed"]
    review_text: str = Field(min_length=1, max_length=30_000)
    publish_date: date | None = None
    date_raw: str | None = None
    likes_count: int = Field(default=0, ge=0)
    meta_info: ReviewMetaInfo = Field(default_factory=ReviewMetaInfo)


class ReviewExtractionRequest(BaseModel):
    business_id: UUID
    content: str = Field(min_length=1, max_length=120_000)
    platform_hint: ReviewPlatform | None = None
    source_url: str | None = None


class ReviewImportRequest(BaseModel):
    business_id: UUID
    reviews: list[ExtractedReview] = Field(min_length=1, max_length=200)


class MentionUpdate(BaseModel):
    author_type: AuthorType | None = None
    include_in_analysis: bool | None = None
    reply_draft: str | None = Field(default=None, max_length=5000)
    reply_status: ReplyStatus | None = None


class ReplyDraftRequest(BaseModel):
    regenerate: bool = False


class ManualImportRequest(BaseModel):
    business_id: UUID
    text: str | None = Field(default=None, max_length=120_000)
    csv_content: str | None = Field(default=None, max_length=2_000_000)
