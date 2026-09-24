"""Bright Data Web Unlocker connector for 2GIS.

This connector implements the minimal path required for the SARAP pipeline to fetch a
2GIS reviews page through Bright Data's **Web Unlocker** REST API. It mirrors the
behaviour of the existing ``TwoGisPlaywrightConnector`` but uses a simple HTTP request
instead of a full browser. All parsing logic stays inside ``extract_reviews_from_html``
so downstream code remains unchanged.

The connector respects the following environment variables (see ``backend/.env.example``):

* ``BRIGHTDATA_API_KEY`` – Bearer token for the Bright Data API.
* ``BRIGHTDATA_UNLOCKER_ZONE`` – The geographic zone (e.g. ``us``) to request the
  unlocker from.

If either variable is missing, a ``ProviderNotConfigured`` exception is raised. HTTP
errors are wrapped in ``ProviderError`` so the fallback pipeline can continue to the
next provider.
"""

from __future__ import annotations

import os
import httpx

from app.connectors.base import BaseConnector
from app.models import ConnectionType, RawItem
from app.connectors.reviews import extract_reviews_from_html, normalize_twogis_business_url
from app.scrapers.fallback import ProviderError, ProviderNotConfigured


class BrightDataTwoGisConnector(BaseConnector):
    """Fetch a 2GIS reviews page via Bright Data Web Unlocker.

    The connector does **not** perform any browser rendering – it simply forwards the
    target URL to Bright Data's ``/request`` endpoint and feeds the returned HTML into
    the existing 2GIS HTML parser.
    """

    source = "2gis"
    connection_type = ConnectionType.monitored
    collection_method = "brightdata"

    def __init__(self, page_url: str, business_id: str = "global") -> None:
        # Normalise the URL to the exact reviews tab – same logic as the direct connector.
        self.page_url = normalize_twogis_business_url(page_url)
        self.business_id = business_id

    async def fetch_latest(self, last_seen_item_id: str | None = None) -> list[RawItem]:
        """Retrieve the raw HTML via Bright Data and parse reviews.

        Args:
            last_seen_item_id: Ignored – the underlying HTML does not contain incremental
                identifiers. The caller will handle deduplication based on ``external_id``.
        Returns:
            A list of :class:`app.models.RawItem` objects compatible with the existing SARAP pipeline.
        """
        api_key = os.getenv("BRIGHTDATA_API_KEY", "").strip()
        zone = os.getenv("BRIGHTDATA_UNLOCKER_ZONE", "").strip()
        if not api_key or not zone:
            raise ProviderNotConfigured("BRIGHTDATA_API_KEY or BRIGHTDATA_UNLOCKER_ZONE is empty")

        endpoint = "https://api.brightdata.com/request"
        headers = {"Authorization": f"Bearer {api_key}"}
        params = {"url": self.page_url, "zone": zone}
        timeout = float(os.getenv("CRAWLER_TIMEOUT_SECONDS", "20"))
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, headers=headers) as client:
                response = await client.get(endpoint, params=params)
                await response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(f"brightdata: {exc}") from exc

        if "text/html" not in response.headers.get("content-type", ""):
            raise ProviderError("brightdata: unexpected content type " + response.headers.get("content-type", ""))

        items = extract_reviews_from_html(response.text, self.page_url, self.source)
        if last_seen_item_id:
            items = items[:
                next(
                    (i for i, it in enumerate(items) if it.external_id == last_seen_item_id),
                    len(items),
                )
            ]
        return items
