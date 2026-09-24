from __future__ import annotations

import asyncio
from collections.abc import Sequence

from supabase import Client, create_client

from app.scrapers.models import ScrapedItem, review_fingerprint


class SupabaseRawReviewStore:
    def __init__(self, url: str, service_role_key: str, business_id: str) -> None:
        if not url or not service_role_key or not business_id:
            raise ValueError("Supabase URL, service role key and business ID are required")
        self.client: Client = create_client(url, service_role_key)
        self.business_id = business_id

    async def existing_fingerprints(
        self,
        source: str,
        page_size: int = 1000,
    ) -> set[str]:
        def fetch() -> set[str]:
            fingerprints: set[str] = set()
            start = 0

            while True:
                response = (
                    self.client.table("raw_reviews")
                    .select("source,author,text_content,rating")
                    .eq("business_id", self.business_id)
                    .eq("source", source)
                    .range(start, start + page_size - 1)
                    .execute()
                )

                rows = response.data or []

                for row in rows:
                    text_content = str(row.get("text_content") or "").strip()

                    if not text_content:
                        continue

                    fingerprints.add(
                        review_fingerprint(
                            str(row.get("source") or source),
                            str(row.get("author") or "Unknown"),
                            text_content,
                            row.get("rating"),
                        )
                    )

                if len(rows) < page_size:
                    break

                start += page_size

            return fingerprints

        return await asyncio.to_thread(fetch)

    async def save(self, items: Sequence[ScrapedItem], batch_size: int = 100) -> int:
        saved = 0
        for start in range(0, len(items), batch_size):
            rows = [item.database_row(self.business_id) for item in items[start:start + batch_size]]
            if not rows:
                continue
            await asyncio.to_thread(
                lambda payload=rows: self.client.table("raw_reviews")
                .upsert(payload, on_conflict="business_id,source,external_id")
                .execute()
            )
            saved += len(rows)
        return saved
