"""Dry-run repair for imported mentions with metadata-backed author/date/summary.

Run locally first:
    python backend/scripts/repair_mentions_metadata_summary.py --business-id <uuid>

Add --apply only after reviewing the printed changes. The script is idempotent:
it does not create mentions, does not touch dedupe/canonical fields, and only
patches author_name, published_at, or ai_analysis.summary when a safer value can
be derived from existing mention text/metadata.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
from typing import Any

from app.repository import repository
from app.services.ai import summarize_review


GENERIC_SUMMARY_PREFIXES = (
    "Пользователь положительно оценивает",
    "Пользователь сообщает о негативном опыте",
    "Пользователь делится мнением",
    "The customer is satisfied",
    "The customer reports a problem",
    "The customer shares a general opinion",
)


def _first(metadata: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = metadata.get(key)
        if value not in (None, "", []):
            return value
    return None


def _parse_date(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if not parsed.tzinfo:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.isoformat()


async def repair(business_id: str, apply: bool) -> None:
    mentions = await repository.request(
        "GET",
        "mentions",
        params={"select": "id,text,author_name,published_at,metadata", "business_id": f"eq.{business_id}", "limit": "10000"},
    )
    changed = 0
    for mention in mentions or []:
        metadata = mention.get("metadata") or {}
        patch: dict[str, Any] = {}
        author = str(_first(metadata, "authorName", "author_name", "author", "username") or "").strip()
        if author and not str(mention.get("author_name") or "").strip():
            patch["author_name"] = author
        published = _parse_date(_first(metadata, "dateCreated", "date_created", "publishedAt", "published_at", "date"))
        if published and not mention.get("published_at"):
            patch["published_at"] = published

        analysis_rows = await repository.request("GET", "ai_analysis", params={"select": "summary,sentiment", "mention_id": f"eq.{mention['id']}", "limit": "1"})
        if analysis_rows:
            current_summary = str(analysis_rows[0].get("summary") or "").strip()
            if not current_summary or current_summary.startswith(GENERIC_SUMMARY_PREFIXES):
                safer_summary = summarize_review(str(mention.get("text") or ""), str(analysis_rows[0].get("sentiment") or "neutral"))
                if safer_summary and safer_summary != current_summary:
                    if apply:
                        await repository.request("PATCH", "ai_analysis", params={"mention_id": f"eq.{mention['id']}"}, json={"summary": safer_summary})
                    patch["_summary"] = safer_summary

        if patch:
            changed += 1
            printable = {key: value for key, value in patch.items() if key != "_summary"}
            if apply and printable:
                await repository.request("PATCH", "mentions", params={"id": f"eq.{mention['id']}"}, json=printable)
            print({"mention_id": mention["id"], "changes": patch})
    print(f"{'Applied' if apply else 'Dry run'}: {changed} mention(s) would be repaired.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--business-id", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    asyncio.run(repair(args.business_id, args.apply))


if __name__ == "__main__":
    main()
