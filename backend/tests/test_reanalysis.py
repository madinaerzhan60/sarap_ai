from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4
import asyncio

from app.services.reanalysis import ANALYSIS_VERSION, reanalyze_mentions


class FakeRepository:
    configured = True

    def __init__(self, mentions: list[dict], analyses: dict[str, dict] | None = None) -> None:
        self.mentions = {str(row["id"]): deepcopy(row) for row in mentions}
        self.analyses = deepcopy(analyses or {})
        self.aspects: dict[str, list[dict]] = {}
        self.risks: dict[str, dict] = {}
        self.calls: list[tuple[str, str, dict | None, object]] = []
        self.recommendations_deleted = False
        self.mention_posts = 0
        self.fail_patch_ids: set[str] = set()

    async def request(self, method: str, path: str, *, params: dict[str, str] | None = None, json=None, prefer: str | None = None):
        self.calls.append((method, path, params, deepcopy(json)))
        if method == "GET" and path == "mentions":
            rows = [
                row for row in self.mentions.values()
                if row["business_id"] == params["business_id"].removeprefix("eq.")
                and row["source"].casefold().startswith("2gis")
                and row["source_type"] == "review"
            ]
            offset = int(params.get("offset", 0))
            limit = int(params.get("limit", 100))
            return deepcopy(rows[offset:offset + limit])
        if method == "GET" and path == "ai_analysis":
            mention_filter = params["mention_id"]
            if mention_filter.startswith("in.("):
                ids = mention_filter.removeprefix("in.(").removesuffix(")").split(",")
                return [deepcopy(self.analyses[item]) for item in ids if item in self.analyses]
            mention_id = mention_filter.removeprefix("eq.")
            return [deepcopy(self.analyses[mention_id])] if mention_id in self.analyses else []
        if method == "PATCH" and path == "mentions":
            mention_id = params["id"].removeprefix("eq.")
            if mention_id in self.fail_patch_ids:
                raise RuntimeError("simulated row failure")
            self.mentions[mention_id].update(deepcopy(json))
            return []
        if method == "POST" and path == "mentions":
            self.mention_posts += 1
            return []
        if method == "POST" and path == "ai_analysis":
            self.analyses[str(json["mention_id"])] = deepcopy(json)
            return []
        if method == "DELETE" and path == "mention_aspects":
            self.aspects[params["mention_id"].removeprefix("eq.")] = []
            return []
        if method == "POST" and path == "mention_aspects":
            for row in json:
                self.aspects.setdefault(str(row["mention_id"]), []).append(deepcopy(row))
            return []
        if method == "POST" and path == "risk_scores":
            self.risks[str(json["mention_id"])] = deepcopy(json)
            return []
        if method == "DELETE" and path == "business_recommendations":
            self.recommendations_deleted = True
            return []
        raise AssertionError(f"Unexpected request: {method} {path} {params} {json}")


def mention_row(**overrides):
    mention_id = str(overrides.pop("id", uuid4()))
    base = {
        "id": mention_id,
        "business_id": str(overrides.pop("business_id", uuid4())),
        "source": "2GIS",
        "source_type": "review",
        "external_id": f"ext-{mention_id}",
        "external_url": None,
        "author_name": "Aigerim",
        "text": "Приемная комиссия в общежитие грубая, ничего нормально не объясняют",
        "rating": 1,
        "published_at": datetime(2026, 1, 5, tzinfo=timezone.utc).isoformat(),
        "collected_at": datetime(2026, 1, 6, tzinfo=timezone.utc).isoformat(),
        "language": "ru",
        "content_hash": f"hash-{mention_id}",
        "dedupe_key": f"dedupe-{mention_id}",
        "is_duplicate": False,
        "duplicate_group_id": None,
        "canonical_mention_id": None,
        "metadata": {"source_connection_id": "source-1", "author_key": "aigerim"},
        "content_type": "review",
        "author_type": "customer",
        "include_in_analysis": True,
        "reply_status": "none",
    }
    base.update(overrides)
    return base


def generic_analysis(mention_id: str) -> dict:
    return {
        "mention_id": mention_id,
        "language": "ru",
        "sentiment": "positive",
        "sentiment_score": 0.8,
        "severity": "low",
        "confidence": 0.9,
        "summary": "Пользователь положительно оценивает сервис.",
        "model": "old",
        "escalated": False,
    }


def test_reanalysis_updates_existing_row_without_duplication_and_preserves_fields():
    business_id = uuid4()
    row = mention_row(business_id=str(business_id))
    original = deepcopy(row)
    repository = FakeRepository([row], {row["id"]: generic_analysis(row["id"])})

    progress = asyncio.run(reanalyze_mentions(repository, business_id=business_id, dry_run=False, batch_size=1))

    assert progress.updated == 1
    assert repository.mention_posts == 0
    updated = repository.mentions[row["id"]]
    for field in ("text", "author_name", "rating", "published_at", "external_id", "source", "dedupe_key", "canonical_mention_id", "duplicate_group_id", "include_in_analysis"):
        assert updated[field] == original[field]
    assert updated["metadata"]["source_connection_id"] == "source-1"
    assert updated["metadata"]["analysis_version"] == ANALYSIS_VERSION
    assert repository.analyses[row["id"]]["summary"] == "Жалуется на грубое общение приемной комиссии общежития и отсутствие понятных объяснений."
    assert repository.analyses[row["id"]]["sentiment"] == "negative"
    assert repository.risks[row["id"]]["score"] >= 60
    assert repository.aspects[row["id"]]


def test_reanalysis_dry_run_reports_without_mutation():
    business_id = uuid4()
    row = mention_row(business_id=str(business_id))
    repository = FakeRepository([row], {row["id"]: generic_analysis(row["id"])})

    progress = asyncio.run(reanalyze_mentions(repository, business_id=business_id, dry_run=True, batch_size=1))

    assert progress.total == 1
    assert progress.stale_found == 1
    assert progress.updated == 1
    assert repository.mentions[row["id"]]["metadata"].get("analysis_version") is None
    assert repository.analyses[row["id"]]["summary"] == "Пользователь положительно оценивает сервис."
    assert not repository.recommendations_deleted


def test_reanalysis_preserves_ignored_state_and_invalidates_recommendations():
    business_id = uuid4()
    row = mention_row(business_id=str(business_id), include_in_analysis=False)
    repository = FakeRepository([row], {row["id"]: generic_analysis(row["id"])})

    progress = asyncio.run(reanalyze_mentions(repository, business_id=business_id, dry_run=False))

    assert progress.updated == 1
    assert repository.mentions[row["id"]]["include_in_analysis"] is False
    assert repository.recommendations_deleted is True


def test_reanalysis_second_stale_only_run_is_idempotent():
    business_id = uuid4()
    row = mention_row(business_id=str(business_id), metadata={"analysis_version": ANALYSIS_VERSION, "source_connection_id": "source-1"})
    repository = FakeRepository([row], {row["id"]: {
        **generic_analysis(row["id"]),
        "summary": "Жалуется на грубое общение приемной комиссии общежития и отсутствие понятных объяснений.",
        "sentiment": "negative",
    }})

    progress = asyncio.run(reanalyze_mentions(repository, business_id=business_id, dry_run=False))

    assert progress.total == 1
    assert progress.processed == 0
    assert progress.skipped == 1
    assert not repository.recommendations_deleted


def test_reanalysis_all_forces_current_version_rows():
    business_id = uuid4()
    row = mention_row(business_id=str(business_id), metadata={"analysis_version": ANALYSIS_VERSION})
    repository = FakeRepository([row], {row["id"]: {
        **generic_analysis(row["id"]),
        "summary": "Жалуется на грубое общение приемной комиссии общежития и отсутствие понятных объяснений.",
        "sentiment": "negative",
    }})

    progress = asyncio.run(reanalyze_mentions(repository, business_id=business_id, stale_only=False, dry_run=False))

    assert progress.processed == 1
    assert progress.updated == 1
    assert repository.recommendations_deleted


def test_reanalysis_continues_after_one_row_failure():
    business_id = uuid4()
    bad = mention_row(business_id=str(business_id))
    good = mention_row(business_id=str(business_id), text="Пофиг всем главное деньги, а не студенты")
    repository = FakeRepository(
        [bad, good],
        {bad["id"]: generic_analysis(bad["id"]), good["id"]: generic_analysis(good["id"])},
    )
    repository.fail_patch_ids.add(bad["id"])

    progress = asyncio.run(reanalyze_mentions(repository, business_id=business_id, dry_run=False, batch_size=2))

    assert progress.failed == 1
    assert progress.updated == 1
    assert progress.failures[0]["mention_id"] == bad["id"]
    assert repository.mentions[good["id"]]["metadata"]["analysis_version"] == ANALYSIS_VERSION
    assert repository.recommendations_deleted
