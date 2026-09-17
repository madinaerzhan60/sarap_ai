from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import httpx

from app.models import AIAnalysis, Aspect, NormalizedMention, ProcessedMention, RiskResult, SourceCreate


class RepositoryUnavailable(RuntimeError):
    pass


class SupabaseRepository:
    def __init__(self) -> None:
        self.url = os.getenv("SUPABASE_URL", "").rstrip("/")
        self.key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

    @property
    def configured(self) -> bool:
        return bool(self.url and self.key)

    def headers(self, prefer: str | None = None) -> dict[str, str]:
        headers = {"apikey": self.key, "Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}
        if prefer:
            headers["Prefer"] = prefer
        return headers

    async def request(self, method: str, path: str, *, params: dict[str, str] | None = None, json: Any = None, prefer: str | None = None) -> Any:
        if not self.configured:
            raise RepositoryUnavailable("SUPABASE_SERVICE_ROLE_KEY is not configured")
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.request(method, f"{self.url}/rest/v1/{path}", params=params, json=json, headers=self.headers(prefer))
        if response.status_code >= 400:
            raise RepositoryUnavailable(f"Supabase {method} {path} failed: {response.text[:300]}")
        return response.json() if response.content else None

    async def find_by_hash(self, business_id: UUID, content_hash: str) -> ProcessedMention | None:
        rows = await self.request("GET", "mentions", params={"select": "id", "business_id": f"eq.{business_id}", "content_hash": f"eq.{content_hash}", "limit": "1"})
        return await self.get_processed(rows[0]["id"]) if rows else None

    async def persist_processed(self, result: ProcessedMention, provider: str = "local") -> ProcessedMention:
        m = result.mention
        existing = await self.find_by_hash(m.business_id, m.content_hash)
        if existing:
            return existing.model_copy(update={"duplicate": True})
        mention_rows = await self.request("POST", "mentions", json={
            "id": str(m.id), "business_id": str(m.business_id), "source": m.source,
            "source_type": m.source_type.value, "external_id": m.external_id,
            "external_url": m.external_url, "author_name": m.author_name, "text": m.text,
            "rating": m.rating, "published_at": m.published_at.isoformat() if m.published_at else None,
            "collected_at": m.collected_at.isoformat(), "language": result.analysis.language,
            "content_hash": m.content_hash, "metadata": m.metadata,
        }, prefer="return=representation")
        mention_id = mention_rows[0]["id"]
        await self.request("POST", "ai_analysis", json={
            "mention_id": mention_id, "language": result.analysis.language,
            "sentiment": result.analysis.sentiment, "sentiment_score": result.analysis.sentiment_score,
            "severity": result.analysis.severity, "confidence": result.analysis.confidence,
            "model": provider, "escalated": result.analysis.escalated,
        })
        if result.analysis.aspects:
            await self.request("POST", "mention_aspects", json=[{"mention_id": mention_id, "aspect": a.aspect, "sentiment": a.sentiment} for a in result.analysis.aspects])
        await self.request("POST", "risk_scores", json={"mention_id": mention_id, "score": result.risk.score, "level": result.risk.level, "reasons": result.risk.reasons})
        if result.alert_created:
            await self.request("POST", "alerts", json={"business_id": str(m.business_id), "mention_id": mention_id, "severity": result.risk.level, "status": "new"})
        await self.request("POST", "ai_usage", json={"business_id": str(m.business_id), "provider": provider, "model": provider, "operation": "mention_analysis"})
        await self.request("PATCH", "businesses", params={"id": f"eq.{m.business_id}"}, json={"last_activity_at": datetime.now(timezone.utc).isoformat()})
        return result

    async def get_processed(self, mention_id: str) -> ProcessedMention | None:
        rows = await self.request("GET", "mentions", params={"select": "*", "id": f"eq.{mention_id}", "limit": "1"})
        if not rows:
            return None
        return await self._hydrate(rows[0])

    async def list_processed(self, business_id: UUID) -> list[ProcessedMention]:
        rows = await self.request("GET", "mentions", params={"select": "*", "business_id": f"eq.{business_id}", "order": "collected_at.desc", "limit": "500"})
        return [await self._hydrate(row) for row in rows]

    async def _hydrate(self, row: dict[str, Any]) -> ProcessedMention:
        mention_id = row["id"]
        analysis_rows, aspect_rows, risk_rows, alert_rows = await __import__("asyncio").gather(
            self.request("GET", "ai_analysis", params={"select": "*", "mention_id": f"eq.{mention_id}", "limit": "1"}),
            self.request("GET", "mention_aspects", params={"select": "*", "mention_id": f"eq.{mention_id}"}),
            self.request("GET", "risk_scores", params={"select": "*", "mention_id": f"eq.{mention_id}", "limit": "1"}),
            self.request("GET", "alerts", params={"select": "id", "mention_id": f"eq.{mention_id}", "limit": "1"}),
        )
        analysis = analysis_rows[0] if analysis_rows else {"language": row.get("language") or "unknown", "sentiment": "neutral", "sentiment_score": 0, "severity": "low", "confidence": 0, "escalated": False}
        risk = risk_rows[0] if risk_rows else {"score": 0, "level": "low", "reasons": []}
        mention = NormalizedMention(**{k: row.get(k) for k in NormalizedMention.model_fields})
        return ProcessedMention(
            mention=mention,
            analysis=AIAnalysis(language=analysis["language"], sentiment=analysis["sentiment"], sentiment_score=float(analysis.get("sentiment_score") or 0), severity=analysis["severity"], confidence=float(analysis.get("confidence") or 0), escalated=analysis.get("escalated", False), aspects=[Aspect(aspect=a["aspect"], sentiment=a["sentiment"]) for a in aspect_rows]),
            risk=RiskResult(score=risk["score"], level=risk["level"], reasons=risk.get("reasons") or []),
            alert_created=bool(alert_rows),
        )

    async def create_source(self, source: SourceCreate) -> dict[str, Any]:
        mode = source.collection_mode.value
        if source.connection_type.value == "imported":
            status = "ready"
        elif mode == "api" and source.connection_type.value == "official":
            status = "oauth_required"
        elif not source.source_url:
            status = "setup_required"
        else:
            status = "active"
        payload = source.model_dump(mode="json") | {"status": status}
        rows = await self.request("POST", "source_connections", json=payload, prefer="return=representation")
        return rows[0]

    async def get_source(self, source_id: str) -> dict[str, Any] | None:
        rows = await self.request("GET", "source_connections", params={"select": "*", "id": f"eq.{source_id}", "limit": "1"})
        return rows[0] if rows else None

    async def update_source(self, source_id: str, values: dict[str, Any]) -> None:
        await self.request("PATCH", "source_connections", params={"id": f"eq.{source_id}"}, json=values)

    async def admin_bundle(self) -> dict[str, Any]:
        businesses = await self.request("GET", "businesses", params={"select": "*", "order": "created_at.desc", "limit": "200"})
        sources = await self.request("GET", "source_connections", params={"select": "*", "order": "updated_at.desc", "limit": "500"})
        usage = await self.request("GET", "ai_usage", params={"select": "*", "order": "created_at.desc", "limit": "500"})
        flags = await self.request("GET", "feature_flags", params={"select": "*", "order": "key"})
        settings = await self.request("GET", "system_settings", params={"select": "*", "order": "key"})
        audit = await self.request("GET", "admin_audit_log", params={"select": "*", "order": "created_at.desc", "limit": "100"})
        return {"businesses": businesses, "sources": sources, "usage": usage, "flags": flags, "settings": settings, "audit": audit}

    async def audit(self, admin_user_id: str, action: str, target_type: str | None = None, target_id: str | None = None, metadata: dict[str, Any] | None = None) -> None:
        await self.request("POST", "admin_audit_log", json={"admin_user_id": admin_user_id, "action": action, "target_type": target_type, "target_id": target_id, "metadata": metadata or {}})


repository = SupabaseRepository()
