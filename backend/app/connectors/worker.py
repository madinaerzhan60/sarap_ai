from __future__ import annotations

import os

import httpx

from app.connectors.base import BaseConnector, ConnectionType
from app.models import RawItem


class ExternalWorkerConnector(BaseConnector):
    """Route browser-heavy collection to a separately deployed worker."""

    connection_type = ConnectionType.monitored
    collection_method = "external_worker"

    def __init__(self, source: str, source_url: str) -> None:
        self.source = source
        self.source_url = source_url

    async def fetch_latest(self, last_seen_item_id: str | None = None) -> list[RawItem]:
        base_url = os.getenv("COLLECTOR_WORKER_URL", "").rstrip("/")
        if not base_url:
            raise RuntimeError("External collector worker is not configured")
        headers = {"Content-Type": "application/json"}
        token = os.getenv("COLLECTOR_WORKER_TOKEN", "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        payload = {"source": self.source, "source_url": self.source_url, "last_seen_external_id": last_seen_item_id, "limit": int(os.getenv("INITIAL_REVIEW_LIMIT", "500"))}
        async with httpx.AsyncClient(timeout=float(os.getenv("COLLECTOR_WORKER_TIMEOUT_SECONDS", "180"))) as client:
            response = await client.post(f"{base_url}/collect", headers=headers, json=payload)
            response.raise_for_status()
        body = response.json()
        if body.get("success") is False:
            raise RuntimeError(str(body.get("error_code") or "worker_failed"))
        return [RawItem.model_validate(item) for item in body.get("items", [])]
