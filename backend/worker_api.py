import os

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from app.connectors.reviews import (
    MapFallbackConnector,
    TwoGisPlaywrightConnector,
)

app = FastAPI(title="SARAP Collector Worker")


class CollectRequest(BaseModel):
    source: str
    source_url: str
    last_seen_external_id: str | None = None
    limit: int = Field(default=500, ge=1, le=10000)


@app.get("/health")
async def health():
    return {"ok": True, "service": "sarap-collector-worker"}


@app.post("/collect")
async def collect(
    request: CollectRequest,
    authorization: str | None = Header(default=None),
):
    expected_token = os.getenv("COLLECTOR_WORKER_TOKEN", "").strip()

    if expected_token:
        if authorization != f"Bearer {expected_token}":
            raise HTTPException(status_code=401, detail="Unauthorized")

    source = request.source.strip().lower()

    try:
        if source == "2gis":
            connector = TwoGisPlaywrightConnector(request.source_url)

        elif source == "yandex_maps":
            connector = MapFallbackConnector(
                "yandex_maps",
                request.source_url,
            )

        elif source == "google_maps":
            connector = MapFallbackConnector(
                "google_maps",
                request.source_url,
            )

        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported worker source: {source}",
            )

        items = await connector.fetch_latest(
            request.last_seen_external_id
        )

        items = items[: request.limit]

        return {
            "success": True,
            "source": source,
            "provider": connector.collection_method,
            "collected": len(items),
            "items": [
                item.model_dump(mode="json")
                for item in items
            ],
        }

    except HTTPException:
        raise

    except Exception as exc:
        return {
            "success": False,
            "source": source,
            "provider": "worker",
            "collected": 0,
            "items": [],
            "error_code": "collection_failed",
            "message": str(exc),
        }
