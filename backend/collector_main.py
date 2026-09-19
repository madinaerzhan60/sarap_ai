from __future__ import annotations

import asyncio
import json
import logging
import os

from dotenv import load_dotenv

from app.collectors.registry import collector_registry
from app.scrapers.models import ScrapedItem
from app.scrapers.storage import SupabaseRawReviewStore


async def main() -> None:
    load_dotenv()
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s %(message)s")
    raw_jobs = json.loads(os.getenv("SCRAPER_JOBS_JSON", "[]"))
    if not raw_jobs:
        raise RuntimeError('SCRAPER_JOBS_JSON must contain jobs, for example [{"source":"2gis","query":"https://..."}]')

    business_id = os.getenv("SCRAPER_BUSINESS_ID", "").strip()
    store = None
    if business_id and os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SERVICE_ROLE_KEY"):
        store = SupabaseRawReviewStore(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"], business_id)
    semaphore = asyncio.Semaphore(int(os.getenv("SCRAPER_MAX_PARALLEL", "3")))

    async def run(row: dict[str, object]) -> dict[str, object]:
        source = {
            "source": str(row["source"]),
            "source_url": str(row.get("query") or row.get("source_url") or ""),
            "collection_mode": str(row.get("collection_mode") or "auto"),
        }
        async with semaphore:
            result = await collector_registry.collect(source)
            saved = 0
            if result.success and store and result.items:
                scraped = [ScrapedItem(
                    source=item.source,
                    author=item.author_name or "Unknown",
                    text_content=item.text,
                    rating=item.rating,
                    published_at=item.published_at,
                    external_id=item.external_id,
                    url=item.external_url,
                    metadata=item.metadata,
                    collected_by=result.provider,
                ) for item in result.items]
                saved = await store.save(scraped)
            return {
                "status": "success" if result.success else "failed",
                "source": result.source,
                "provider": result.provider,
                "collected": result.collected_count,
                "saved": saved,
                "warnings": result.warnings,
                "error_code": result.error_code,
                "message": result.error_message,
            }

    results = await asyncio.gather(*(run(row) for row in raw_jobs))
    print(json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
