from __future__ import annotations

import os
from datetime import datetime

from .base import BaseConnector
from .zenrows_twogis import ZenRowsTwoGisConnector
from .demo import DemoGoogleConnector, DemoTwoGisConnector
from .feeds import MonitoredPageConnector, RssConnector

from app.models import ConnectionType, MentionType, RawItem
import app.scrapers.fallback as fallback
from app.scrapers.fallback import _datetime


def _apify_items_to_raw(source: str, source_type: MentionType, scraped: list, provider: str, content_type: str, rating_allowed: bool) -> list[RawItem]:
    items: list[RawItem] = []
    for item in scraped:
        rating = item.rating if rating_allowed else None
        metadata = {**item.metadata, "language": item.language, "collected_by": provider, "content_type": content_type}
        items.append(RawItem(
            source=source,
            source_type=source_type,
            external_id=item.stable_id(),
            external_url=item.url,
            author_name=None if item.author == "Unknown" else item.author,
            text=item.text_content,
            rating=rating,
            published_at=item.published_at,
            metadata=metadata,
        ))
    return items


class _ApifyConnector(BaseConnector):
    connection_type = ConnectionType.monitored
    collection_method = "apify"
    platform = ""
    source = ""
    actor_env = ""
    input_env = ""
    source_type = MentionType.social_post
    content_type = "post"
    rating_allowed = False
    limit_env = "APIFY_MAX_ITEMS_PER_RUN"
    default_limit = 500

    def __init__(self, page_url: str, business_id: str = "global") -> None:
        self.page_url = page_url
        self.business_id = business_id

    async def fetch_latest(self, last_seen_item_id: str | None = None) -> list[RawItem]:
        apify = fallback.ApifyProvider(
            self.platform,
            actor_id=fallback.get_apify_actor_id(self.platform, self.actor_env),
            input_json=os.getenv(self.input_env),
            require_paid_opt_in=False,
        )
        pipeline = fallback.FallbackPipeline(self.platform, [apify], business_id=self.business_id)
        if not getattr(pipeline, "items", None) and hasattr(pipeline.__class__, "items"):
            pipeline.items = pipeline.__class__.items
        scraped, provider, failures = await pipeline.collect_items(self.page_url, limit=int(os.getenv(self.limit_env, str(self.default_limit))))
        if not provider:
            detail = "; ".join(f"{row['provider']}: {row['error']}" for row in failures)
            raise fallback.ProviderError(f"{self.source.title()} collection failed through every configured method. {detail}")
        self.collection_method = provider
        self.confirmed_empty = not scraped
        items = _apify_items_to_raw(self.source, self.source_type, scraped, provider, self.content_type, self.rating_allowed)
        if last_seen_item_id:
            items = items[: next((i for i, it in enumerate(items) if it.external_id == last_seen_item_id), len(items))]
        return items


class InstagramApifyConnector(_ApifyConnector):
    """Collect public Instagram posts/comments through Apify provider.

    Respects optional date window via INSTAGRAM_DATE_FROM and INSTAGRAM_DATE_TO.
    """
    source = "instagram"
    platform = "instagram"
    actor_env = "APIFY_INSTAGRAM_ACTOR_ID"
    input_env = "APIFY_INSTAGRAM_INPUT_JSON"
    source_type = MentionType.social_comment
    content_type = "comment"

    async def fetch_latest(self, last_seen_item_id: str | None = None) -> list[RawItem]:
        items = await super().fetch_latest(last_seen_item_id)
        date_from_str = os.getenv("INSTAGRAM_DATE_FROM", "").strip()
        date_to_str = os.getenv("INSTAGRAM_DATE_TO", "").strip()
        date_from = datetime.fromisoformat(date_from_str) if date_from_str else None
        date_to = datetime.fromisoformat(date_to_str) if date_to_str else None

        def within_window(item: RawItem) -> bool:
            if not date_from and not date_to:
                return True
            published = _datetime(item.published_at)
            if not published:
                return False
            if date_from and published < date_from:
                return False
            if date_to and published > date_to:
                return False
            return True

        return [item for item in items if within_window(item)]


class FacebookApifyConnector(_ApifyConnector):
    """Collect public Facebook posts/comments through Apify provider.

    Respects optional date window via FACEBOOK_DATE_FROM and FACEBOOK_DATE_TO.
    """
    source = "facebook"
    platform = "facebook"
    actor_env = "APIFY_FACEBOOK_ACTOR_ID"
    input_env = "APIFY_FACEBOOK_INPUT_JSON"
    source_type = MentionType.social_post
    content_type = "post"

    async def fetch_latest(self, last_seen_item_id: str | None = None) -> list[RawItem]:
        items = await super().fetch_latest(last_seen_item_id)
        date_from_str = os.getenv("FACEBOOK_DATE_FROM", "").strip()
        date_to_str = os.getenv("FACEBOOK_DATE_TO", "").strip()
        date_from = datetime.fromisoformat(date_from_str) if date_from_str else None
        date_to = datetime.fromisoformat(date_to_str) if date_to_str else None

        def within_window(item: RawItem) -> bool:
            if not date_from and not date_to:
                return True
            published = _datetime(item.published_at)
            if not published:
                return False
            if date_from and published < date_from:
                return False
            if date_to and published > date_to:
                return False
            return True

        return [item for item in items if within_window(item)]


class YouTubeApifyConnector(_ApifyConnector):
    source = "youtube"
    platform = "youtube"
    actor_env = "APIFY_YOUTUBE_ACTOR_ID"
    input_env = "APIFY_YOUTUBE_INPUT_JSON"
    source_type = MentionType.video_comment
    content_type = "comment"
    limit_env = "YOUTUBE_COMMENTS_PER_SYNC"
    default_limit = 100


class YandexApifyConnector(_ApifyConnector):
    source = "yandex_maps"
    platform = "yandex_maps"
    actor_env = "APIFY_YANDEX_ACTOR_ID"
    input_env = "APIFY_YANDEX_INPUT_JSON"
    source_type = MentionType.review
    content_type = "review"
    rating_allowed = True

__all__ = [
    "BaseConnector",
    "DemoGoogleConnector",
    "DemoTwoGisConnector",
    "MonitoredPageConnector",
    "RssConnector",
    "ZenRowsTwoGisConnector",
    "InstagramApifyConnector",
    "FacebookApifyConnector",
    "YouTubeApifyConnector",
    "YandexApifyConnector",
]
