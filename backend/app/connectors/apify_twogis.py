"""Apify connector for 2GIS reviews using ready-made Actor."""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from app.connectors.base import BaseConnector
from app.connectors.reviews import normalize_twogis_business_url
from app.models import ConnectionType, MentionType, RawItem
from app.scrapers.fallback import ProviderError, ProviderNotConfigured, get_apify_actor_id, get_apify_token

logger = logging.getLogger("sarap.connectors.apify_twogis")


def _parse_iso_date(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        # Standard ISO string parsing
        clean_val = value.replace("Z", "+00:00")
        return datetime.fromisoformat(clean_val)
    except (ValueError, TypeError):
        return None


class ApifyTwoGisConnector(BaseConnector):
    """Fetch 2GIS reviews directly through Apify 2GIS Reviews Scraper Actor."""

    source = "2gis"
    connection_type = ConnectionType.monitored
    collection_method = "apify"

    def __init__(self, page_url: str, business_id: str = "global") -> None:
        self.page_url = normalize_twogis_business_url(page_url)
        self.business_id = business_id

    async def fetch_latest(self, last_seen_item_id: str | None = None, backfill: bool = False) -> list[RawItem]:
        token = get_apify_token()
        if not token:
            raise ProviderNotConfigured("APIFY_API_TOKEN, APIFY_TOKEN, or APIFY_API_KEY is empty")

        actor_id = get_apify_actor_id("2GIS", "APIFY_TWOGIS_ACTOR_ID", "APIFY_2GIS_ACTOR_ID", default="zen-studio/2gis-reviews-scraper")
        actor_path = actor_id.replace("/", "~")
        endpoint = f"https://api.apify.com/v2/acts/{actor_path}/run-sync-get-dataset-items"

        maximum = 1000 if backfill else int(os.getenv("APIFY_MAX_ITEMS_PER_RUN", "200"))
        
        # Build payload according to actor expectations
        if actor_id == "getascraper/2gis-reviews-scraper":
            firm_match = re.search(r"/firm/(\d+)", self.page_url)
            if firm_match:
                payload = {
                    "firmIds": [firm_match.group(1)],
                    "urls": [],
                    "maxItemsPerFirm": maximum,
                    "withTextOnly": False,
                    "includeRawData": False,
                }
            else:
                payload = {"startUrls": [{"url": self.page_url}], "maxItems": maximum}
        else:
            # Primary: zen-studio/2gis-reviews-scraper
            payload = {
                "startUrls": [{"url": self.page_url}],
                "maxReviews": maximum,
            }

        timeout_seconds = int(os.getenv("APIFY_RUN_TIMEOUT_SECONDS", "300"))
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds + 30) as client:
                response = await client.post(
                    endpoint,
                    params={"token": token, "timeout": timeout_seconds, "clean": "true"},
                    json=payload,
                )
                if response.status_code not in (200, 201):
                    raise ProviderError(f"apify: HTTP {response.status_code} - {response.text[:200]}")
        except httpx.HTTPError as exc:
            raise ProviderError(f"apify network error: {exc}") from exc

        rows = response.json()
        if not isinstance(rows, list):
            raise ProviderError("apify: actor returned non-list response")

        items: list[RawItem] = []
        for row in rows:
            if not isinstance(row, dict):
                continue

            text = str(row.get("text") or row.get("reviewText") or row.get("comment") or "").strip()
            if not text:
                continue

            review_id = str(row.get("reviewId") or row.get("id") or "").strip()
            author_name = str(row.get("authorName") or row.get("authorFirstName") or row.get("author") or "").strip() or None
            
            raw_rating = row.get("rating") if row.get("rating") is not None else row.get("stars")
            rating = float(raw_rating) if raw_rating is not None and str(raw_rating).replace(".", "", 1).isdigit() else None

            pub_date = _parse_iso_date(row.get("dateCreated") or row.get("date") or row.get("publishedAt"))

            ext_id = review_id if review_id else f"apify-{hash(text)}"
            review_url = str(row.get("reviewUrl") or "").strip() or f"{self.page_url}#review-{ext_id}"

            metadata: dict[str, Any] = {
                "content_type": "review",
                "collected_by": "apify",
                "actor_id": actor_id,
                "place_id": row.get("placeId"),
                "place_rating": row.get("placeRating"),
                "place_review_count": row.get("placeReviewCount"),
                "official_answer": row.get("officialAnswer"),
                "likes_count": row.get("likesCount", 0),
            }

            items.append(
                RawItem(
                    source=self.source,
                    source_type=MentionType.review,
                    external_id=ext_id,
                    external_url=review_url,
                    author_name=author_name,
                    text=text,
                    rating=rating,
                    published_at=pub_date,
                    metadata=metadata,
                )
            )

        # Handle last_seen_item_id incremental cutoff
        if last_seen_item_id and not backfill:
            cutoff = next((i for i, item in enumerate(items) if item.external_id == last_seen_item_id), None)
            if cutoff is not None:
                items = items[:cutoff]
                if not items:
                    self.confirmed_empty = True

        return items
