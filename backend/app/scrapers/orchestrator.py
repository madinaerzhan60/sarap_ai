from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from app.scrapers.base import BaseScraper


@dataclass(frozen=True)
class ScrapeJob:
    scraper: BaseScraper
    query: str
    limit: int = 50


class ScrapeOrchestrator:
    def __init__(self, max_parallel_sources: int = 3) -> None:
        self.semaphore = asyncio.Semaphore(max_parallel_sources)
        self.log = logging.getLogger("sarap.scraper.orchestrator")

    async def _run_job(self, job: ScrapeJob) -> dict[str, object]:
        async with self.semaphore:
            try:
                collected, saved = await job.scraper.run(job.query, job.limit)
                return {"source": job.scraper.source, "status": "ok", "collected": collected, "saved": saved}
            except Exception as exc:
                self.log.exception("Source %s failed", job.scraper.source)
                return {"source": job.scraper.source, "status": "error", "error": str(exc)}

    async def run(self, jobs: list[ScrapeJob]) -> list[dict[str, object]]:
        return await asyncio.gather(*(self._run_job(job) for job in jobs))
