from __future__ import annotations

from app.connectors.base import BaseConnector
from app.models import ConnectionType, MentionType, RawItem


class DemoTwoGisConnector(BaseConnector):
    source = "2gis"
    connection_type = ConnectionType.monitored

    async def fetch_latest(self, last_seen_item_id: str | None = None) -> list[RawItem]:
        items = [
            RawItem(
                source=self.source,
                source_type=MentionType.review,
                external_id="2gis-demo-002",
                external_url="https://2gis.kz/almaty/firm/demo/tab/reviews",
                author_name="Nurlan B.",
                text="Кофе күшті, бірақ кассир қыз өте дөрекі екен.",
                rating=3,
            ),
            RawItem(
                source=self.source,
                source_type=MentionType.review,
                external_id="2gis-demo-001",
                author_name="Aliya S.",
                text="Керемет орын, тағы да келемін!",
                rating=5,
            ),
        ]
        if last_seen_item_id:
            items = items[: next((i for i, x in enumerate(items) if x.external_id == last_seen_item_id), len(items))]
        return items


class DemoGoogleConnector(BaseConnector):
    """Official connector boundary; replace demo payload with OAuth/API calls."""

    source = "google_business"
    connection_type = ConnectionType.official

    async def fetch_latest(self, last_seen_item_id: str | None = None) -> list[RawItem]:
        return []
