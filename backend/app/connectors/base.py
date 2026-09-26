from __future__ import annotations

from abc import ABC, abstractmethod

from app.models import ConnectionType, RawItem


class BaseConnector(ABC):
    """Replaceable ingestion boundary. Connectors never run business analysis."""

    source: str
    connection_type: ConnectionType

    @abstractmethod
    async def fetch_latest(self, last_seen_item_id: str | None = None, *, backfill: bool = False) -> list[RawItem]:
        """Return newest-first items and stop after the known external ID."""

    async def health(self) -> dict[str, str]:
        return {"source": self.source, "status": "ready", "mode": self.connection_type}
