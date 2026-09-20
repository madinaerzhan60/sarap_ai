from __future__ import annotations

from urllib.parse import urlparse

from app.connectors.base import BaseConnector, ConnectionType
from app.connectors.search import DiscoveryService
from app.models import MentionType, RawItem


class PublicDiscoveryConnector(BaseConnector):
    """Collect indexed public mentions for sources without an MVP OAuth connector."""

    connection_type = ConnectionType.monitored
    collection_method = "discovery"

    def __init__(self, source: str, page_url: str) -> None:
        self.source = source
        self.page_url = page_url
        parsed = urlparse(page_url)
        path_name = parsed.path.strip("/").split("/")[-1].replace("-", " ").replace("_", " ")
        self.query = path_name or parsed.hostname or source

    async def fetch_latest(self, last_seen_item_id: str | None = None) -> list[RawItem]:
        results, _ = await DiscoveryService().search_many(
            [f'"{self.query}" site:{urlparse(self.page_url).hostname}'], country="KZ", date_range="30d"
        )
        items = [RawItem(
            source=self.source,
            source_type=MentionType.social_post,
            external_id=result.url,
            external_url=result.url,
            author_name=result.source,
            text=result.snippet or result.title,
            published_at=result.published_at,
            metadata={"title": result.title, "collection_method": "discovery"},
        ) for result in results]
        if last_seen_item_id:
            items = items[:next((index for index, item in enumerate(items) if item.external_id == last_seen_item_id), len(items))]
        return items
