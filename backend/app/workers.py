from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Awaitable, Callable
from uuid import UUID, uuid4


class JobType(StrEnum):
    poll_source = "poll_source"
    process_mention = "process_mention"
    run_ai_analysis = "run_ai_analysis"
    calculate_risk = "calculate_risk"
    send_alert = "send_alert"
    web_discovery = "web_discovery"
    daily_summary = "daily_summary"


@dataclass
class Job:
    type: JobType
    payload: dict[str, Any]
    id: UUID = field(default_factory=uuid4)
    run_after: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    attempts: int = 0


class InProcessQueue:
    """Readable in-process queue. Replace it with a durable queue before scaling workers."""

    def __init__(self) -> None:
        self.jobs: list[Job] = []

    def enqueue(self, type_: JobType, payload: dict[str, Any]) -> Job:
        job = Job(type=type_, payload=payload)
        self.jobs.append(job)
        return job

    async def run_once(self, handlers: dict[JobType, Callable[[dict[str, Any]], Awaitable[None]]]) -> int:
        now = datetime.now(timezone.utc)
        ready = [job for job in self.jobs if job.run_after <= now]
        for job in ready:
            handler = handlers.get(job.type)
            if handler:
                await handler(job.payload)
            self.jobs.remove(job)
        return len(ready)
