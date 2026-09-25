"""ZenRows connector for 2GIS reviews."""

from __future__ import annotations

import os

import httpx

from app.connectors.base import BaseConnector
from app.connectors.reviews import extract_reviews_from_html, normalize_twogis_business_url
from app.models import ConnectionType, RawItem
from app.scrapers.fallback import ProviderError, ProviderNotConfigured


class ZenRowsTwoGisConnector(BaseConnector):
    """Fetch a 2GIS reviews page through ZenRows and reuse the existing parser."""

    source = "2gis"
    connection_type = ConnectionType.monitored
    collection_method = "zenrows"

    def __init__(self, page_url: str, business_id: str = "global") -> None:
        self.page_url = normalize_twogis_business_url(page_url)
        self.business_id = business_id

    async def fetch_latest(self, last_seen_item_id: str | None = None) -> list[RawItem]:
        api_key = os.getenv("ZENROWS_API_KEY", "").strip()
        if not api_key:
            raise ProviderNotConfigured("ZENROWS_API_KEY is empty")

        timeout = float(os.getenv("CRAWLER_TIMEOUT_SECONDS", "20"))
        params = {
            "url": self.page_url,
            "apikey": api_key,
            "js_render": "true",
            "premium_proxy": "true",
        }
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
                response = await client.get("https://api.zenrows.com/v1/", params=params)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(f"zenrows: {exc}") from exc

        content_type = response.headers.get("content-type", "")
        if "text/html" not in content_type:
            raise ProviderError(f"zenrows: unexpected content type {content_type}")

        html = response.text.strip()
        if not html:
            raise ProviderError("zenrows: empty response")
        if _looks_blocked(html):
            raise ProviderError("zenrows: blocked or captcha response")

        items = extract_reviews_from_html(html, self.page_url, self.source)
        if not items:
            raise ProviderError("zenrows: no usable 2GIS reviews found in response")
        if last_seen_item_id:
            items = items[
                : next(
                    (i for i, item in enumerate(items) if item.external_id == last_seen_item_id),
                    len(items),
                )
            ]
        return items


def _looks_blocked(html: str) -> bool:
    normalized = html.lower()
    return any(
        marker in normalized
        for marker in (
            "captcha",
            "cloudflare",
            "access denied",
            "are you a human",
            "verify you are human",
            "unusual traffic",
        )
    )
