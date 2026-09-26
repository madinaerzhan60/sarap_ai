from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

from app.models import MentionType, NormalizedMention, ProcessedMention
from app.services.ai import analyze
from app.services.risk import calculate

ANALYSIS_VERSION = 2

GENERIC_OLD_SUMMARIES = {
    "пользователь положительно оценивает сервис.",
    "пользователь сообщает о негативном опыте с сервисом.",
    "пользователь делится мнением без однозначной оценки.",
    "the customer is satisfied with the overall experience.",
    "the customer reports a problem with the experience.",
}


class ReanalysisRepository(Protocol):
    configured: bool

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: Any = None,
        prefer: str | None = None,
    ) -> Any: ...


@dataclass
class ReanalysisProgress:
    total: int = 0
    stale_found: int = 0
    processed: int = 0
    updated: int = 0
    failed: int = 0
    skipped: int = 0
    dry_run: bool = True
    failures: list[dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "stale_found": self.stale_found,
            "processed": self.processed,
            "updated": self.updated,
            "failed": self.failed,
            "skipped": self.skipped,
            "dry_run": self.dry_run,
            "failures": self.failures[:20],
        }


def is_stale_analysis(mention: dict[str, Any], analysis: dict[str, Any] | None) -> bool:
    metadata = mention.get("metadata") or {}
    if metadata.get("analysis_version") != ANALYSIS_VERSION:
        return True
    summary = str((analysis or {}).get("summary") or "").strip().casefold()
    return summary in GENERIC_OLD_SUMMARIES


def _source_filter(source: str) -> str:
    normalized = source.strip()
    return "2gis*" if normalized.casefold() in {"2gis", "2gis maps"} else normalized


async def _fetch_batch(repository: ReanalysisRepository, business_id: UUID, source: str, offset: int, limit: int) -> list[dict[str, Any]]:
    return await repository.request(
        "GET",
        "mentions",
        params={
            "select": "*",
            "business_id": f"eq.{business_id}",
            "source": f"ilike.{_source_filter(source)}",
            "source_type": f"eq.{MentionType.review.value}",
            "order": "collected_at.asc",
            "limit": str(limit),
            "offset": str(offset),
        },
    ) or []


async def _fetch_analysis_map(repository: ReanalysisRepository, mention_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not mention_ids:
        return {}
    rows = await repository.request(
        "GET",
        "ai_analysis",
        params={"select": "*", "mention_id": f"in.({','.join(mention_ids)})"},
    ) or []
    return {str(row["mention_id"]): row for row in rows}


def _mention_from_row(row: dict[str, Any], analysis: Any) -> NormalizedMention:
    values = {key: row[key] for key in NormalizedMention.model_fields if key in row and row[key] is not None}
    values["language"] = getattr(analysis, "language", None) or row.get("language")
    return NormalizedMention(**values)


async def _apply_update(repository: ReanalysisRepository, mention: NormalizedMention, result: ProcessedMention) -> None:
    mention_id = str(mention.id)
    await repository.request("POST", "ai_analysis", params={"on_conflict": "mention_id"}, json={
        "mention_id": mention_id,
        "language": result.analysis.language,
        "sentiment": result.analysis.sentiment,
        "sentiment_score": result.analysis.sentiment_score,
        "severity": result.analysis.severity,
        "confidence": result.analysis.confidence,
        "summary": result.analysis.summary,
        "model": f"local-v{ANALYSIS_VERSION}",
        "escalated": result.analysis.escalated,
    }, prefer="resolution=merge-duplicates")
    await repository.request("DELETE", "mention_aspects", params={"mention_id": f"eq.{mention_id}"})
    if result.analysis.aspects:
        await repository.request("POST", "mention_aspects", json=[
            {"mention_id": mention_id, "aspect": aspect.aspect, "sentiment": aspect.sentiment}
            for aspect in result.analysis.aspects
        ])
    await repository.request("POST", "risk_scores", params={"on_conflict": "mention_id"}, json={
        "mention_id": mention_id,
        "score": result.risk.score,
        "level": result.risk.level,
        "reasons": result.risk.reasons,
    }, prefer="resolution=merge-duplicates")
    await repository.request("PATCH", "mentions", params={"id": f"eq.{mention_id}"}, json={
        "language": result.analysis.language,
        "metadata": {**mention.metadata, "analysis_version": ANALYSIS_VERSION},
    })


async def _invalidate_recommendation_cache(repository: ReanalysisRepository, business_id: UUID) -> None:
    try:
        await repository.request("DELETE", "business_recommendations", params={"business_id": f"eq.{business_id}"})
    except Exception:
        return


async def reanalyze_mentions(
    repository: ReanalysisRepository,
    *,
    business_id: UUID,
    source: str = "2gis",
    stale_only: bool = True,
    dry_run: bool = True,
    batch_size: int = 100,
) -> ReanalysisProgress:
    progress = ReanalysisProgress(dry_run=dry_run)
    offset = 0
    batch_size = max(1, min(batch_size, 500))

    while True:
        batch = await _fetch_batch(repository, business_id, source, offset, batch_size)
        if not batch:
            break
        progress.total += len(batch)
        analysis_by_id = await _fetch_analysis_map(repository, [str(row["id"]) for row in batch])
        for row in batch:
            mention_id = str(row.get("id"))
            analysis_row = analysis_by_id.get(mention_id)
            stale = is_stale_analysis(row, analysis_row)
            if stale:
                progress.stale_found += 1
            if stale_only and not stale:
                progress.skipped += 1
                continue
            progress.processed += 1
            try:
                new_analysis = analyze(str(row.get("text") or ""), row.get("rating"))
                mention = _mention_from_row(row, new_analysis)
                new_risk = calculate(mention, new_analysis)
                result = ProcessedMention(mention=mention, analysis=new_analysis, risk=new_risk, alert_created=False)
                if not dry_run:
                    await _apply_update(repository, mention, result)
                progress.updated += 1
            except Exception as exc:  # noqa: BLE001 - batch jobs must continue after a bad row.
                progress.failed += 1
                progress.failures.append({"mention_id": mention_id, "error": str(exc)[:300]})
        offset += len(batch)

    if not dry_run and progress.updated:
        await _invalidate_recommendation_cache(repository, business_id)
    return progress


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Safely re-run SARAP analysis for existing stored mentions.")
    parser.add_argument("--business-id", required=True, type=UUID)
    parser.add_argument("--source", default="2gis")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--stale-only", action="store_true", help="Only process stale/generic analysis rows. Default.")
    mode.add_argument("--all", action="store_true", help="Force reanalyze all matching mentions.")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--apply", action="store_true", help="Persist updates. Without this flag the job is a dry run.")
    return parser


async def run_cli(args: argparse.Namespace) -> ReanalysisProgress:
    from app.repository import repository

    if not repository.configured:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be configured")
    progress = await reanalyze_mentions(
        repository,
        business_id=args.business_id,
        source=args.source,
        stale_only=not args.all,
        dry_run=not args.apply,
        batch_size=args.batch_size,
    )
    return progress


def main() -> None:
    args = build_arg_parser().parse_args()
    progress = asyncio.run(run_cli(args))
    print(
        f"dry_run={progress.dry_run} processed={progress.processed}/{progress.total} "
        f"stale={progress.stale_found} updated={progress.updated} "
        f"failed={progress.failed} skipped={progress.skipped}"
    )
    for failure in progress.failures[:20]:
        print(f"failed mention_id={failure['mention_id']} error={failure['error']}")


if __name__ == "__main__":
    main()
