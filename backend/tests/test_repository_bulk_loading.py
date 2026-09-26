from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from app.repository import SupabaseRepository


class BulkRepository(SupabaseRepository):
    def __init__(self, mention_count: int) -> None:
        super().__init__()
        self.business_id = uuid4()
        self.calls: list[tuple[str, str, dict]] = []
        self.mentions = [_mention_row(self.business_id, index) for index in range(mention_count)]
        self.analysis = {
            row["id"]: {
                "mention_id": row["id"],
                "language": "ru",
                "sentiment": "positive" if index % 2 else "negative",
                "summary": f"summary {index}",
                "sentiment_score": 0.7,
                "severity": "low",
                "confidence": 0.9,
                "escalated": False,
            }
            for index, row in enumerate(self.mentions)
        }
        self.aspects = [
            {"mention_id": row["id"], "aspect": "campus_atmosphere", "sentiment": self.analysis[row["id"]]["sentiment"]}
            for row in self.mentions
        ]
        self.risks = {
            row["id"]: {"mention_id": row["id"], "score": 10, "level": "Low", "reasons": []}
            for row in self.mentions
        }
        self.alerts = [{"id": str(uuid4()), "mention_id": self.mentions[0]["id"]}]

    @property
    def configured(self) -> bool:
        return True

    async def request(self, method: str, path: str, *, params=None, json=None, prefer=None):
        self.calls.append((method, path, dict(params or {})))
        if path == "mentions":
            return self.mentions
        ids = _ids_from_filter(params["mention_id"])
        if path == "ai_analysis":
            return [self.analysis[item] for item in ids if item in self.analysis]
        if path == "mention_aspects":
            return [item for item in self.aspects if item["mention_id"] in ids]
        if path == "risk_scores":
            return [self.risks[item] for item in ids if item in self.risks]
        if path == "alerts":
            return [item for item in self.alerts if item["mention_id"] in ids]
        raise AssertionError(f"Unexpected request: {method} {path}")


def _mention_row(business_id, index: int) -> dict:
    mention_id = str(uuid4())
    now = datetime(2026, 9, 27, tzinfo=timezone.utc).isoformat()
    return {
        "id": mention_id,
        "business_id": str(business_id),
        "source": "2GIS",
        "source_type": "review",
        "external_id": f"ext-{index}",
        "external_url": None,
        "author_name": f"Author {index}",
        "text": f"Review text {index}",
        "rating": 5,
        "published_at": now,
        "collected_at": now,
        "language": "ru",
        "content_hash": f"hash-{index}",
        "dedupe_key": f"dedupe-{index}",
        "is_duplicate": False,
        "duplicate_group_id": None,
        "canonical_mention_id": None,
        "metadata": {},
        "content_type": "review",
        "author_type": "customer",
        "include_in_analysis": True,
        "reply_status": "none",
    }


def _ids_from_filter(value: str) -> list[str]:
    assert value.startswith("in.(")
    return value.removeprefix("in.(").removesuffix(")").split(",")


def test_list_processed_bulk_loads_related_rows_for_400_plus_mentions():
    repository = BulkRepository(405)

    rows = asyncio.run(repository.list_processed(repository.business_id))

    assert len(rows) == 405
    assert rows[0].analysis.summary == "summary 0"
    assert rows[0].analysis.aspects[0].aspect == "campus_atmosphere"
    assert rows[0].risk.score == 10
    assert rows[0].alert_created is True
    assert rows[1].alert_created is False

    paths = [path for _, path, _ in repository.calls]
    assert paths.count("mentions") == 1
    assert paths.count("ai_analysis") == 3
    assert paths.count("mention_aspects") == 3
    assert paths.count("risk_scores") == 3
    assert paths.count("alerts") == 3
    assert len(repository.calls) == 13
    assert not any(params.get("mention_id", "").startswith("eq.") for _, _, params in repository.calls)
