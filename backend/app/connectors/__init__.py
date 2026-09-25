from __future__ import annotations

import os
from datetime import datetime

from .base import BaseConnector
from .zenrows_twogis import ZenRowsTwoGisConnector
from .demo import DemoGoogleConnector, DemoTwoGisConnector
from .feeds import MonitoredPageConnector, RssConnector

from app.models import ConnectionType, RawItem
import app.scrapers.fallback as fallback
from app.scrapers.fallback import _datetime


class InstagramApifyConnector(BaseConnector):
    """Collect public Instagram posts/comments through Apify provider.

    Respects optional date window via INSTAGRAM_DATE_FROM and INSTAGRAM_DATE_TO.
    """
    source = "instagram"
    connection_type = ConnectionType.monitored
    collection_method = "apify"

    def __init__(self, page_url: str, business_id: str = "global") -> None:
        self.page_url = page_url
        self.business_id = business_id

    async def fetch_latest(self, last_seen_item_id: str | None = None) -> list[RawItem]:
        apify = fallback.ApifyProvider(
            "instagram",
            os.getenv("APIFY_TOKEN"),
            os.getenv("APIFY_INSTAGRAM_ACTOR_ID"),
            os.getenv("APIFY_INSTAGRAM_INPUT_JSON"),
        )
        pipeline = fallback.FallbackPipeline("instagram", [apify], business_id=self.business_id)
        # If using the DummyPipeline in tests, class-level `items` may be set. Ensure they are used.
        if not getattr(pipeline, "items", None) and hasattr(pipeline.__class__, "items"):
            pipeline.items = pipeline.__class__.items
        scraped, provider, failures = await pipeline.collect_items(self.page_url, limit=500)
        if not provider:
            detail = "; ".join(f"{row['provider']}: {row['error']}" for row in failures)
            raise fallback.ProviderError(
                f"Instagram collection failed through every configured method. {detail}"
            )
        self.collection_method = provider
        self.confirmed_empty = not scraped

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

        items = [item for item in scraped if within_window(item)]
        if last_seen_item_id:
            items = items[: next((i for i, it in enumerate(items) if it.external_id == last_seen_item_id), len(items))]
        return items


class FacebookApifyConnector(BaseConnector):
    """Collect public Facebook posts/comments through Apify provider.

    Respects optional date window via FACEBOOK_DATE_FROM and FACEBOOK_DATE_TO.
    """
    source = "facebook"
    connection_type = ConnectionType.monitored
    collection_method = "apify"

    def __init__(self, page_url: str, business_id: str = "global") -> None:
        self.page_url = page_url
        self.business_id = business_id

    async def fetch_latest(self, last_seen_item_id: str | None = None) -> list[RawItem]:
        # Ensure APIFY_TOKEN is configured; otherwise raise ProviderNotConfigured
        if not os.getenv("APIFY_TOKEN"):
            raise fallback.ProviderNotConfigured("Facebook Apify provider not configured: missing APIFY_TOKEN")
        apify = fallback.ApifyProvider(
            "facebook",
            os.getenv("APIFY_TOKEN"),
            os.getenv("APIFY_FACEBOOK_ACTOR_ID"),
            os.getenv("APIFY_FACEBOOK_INPUT_JSON"),
        )
        pipeline = fallback.FallbackPipeline("facebook", [apify], business_id=self.business_id)
        scraped, provider, failures = await pipeline.collect_items(self.page_url, limit=500)
        if not provider:
            detail = "; ".join(f"{row['provider']}: {row['error']}" for row in failures)
            raise fallback.ProviderError(
                f"Facebook collection failed through every configured method. {detail}"
            )
        self.collection_method = provider
        self.confirmed_empty = not scraped

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

        items = [item for item in scraped if within_window(item)]
        if last_seen_item_id:
            items = items[: next((i for i, it in enumerate(items) if it.external_id == last_seen_item_id), len(items))]
        return items

__all__ = [
    "BaseConnector",
    "DemoGoogleConnector",
    "DemoTwoGisConnector",
    "MonitoredPageConnector",
    "RssConnector",
    "ZenRowsTwoGisConnector",
    "InstagramApifyConnector",
    "FacebookApifyConnector",
]
