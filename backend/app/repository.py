from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import httpx

from app.models import AIAnalysis, Aspect, NormalizedMention, ProcessedMention, RiskResult, SourceCreate


class RepositoryUnavailable(RuntimeError):
    pass


class SourceAlreadyConnected(RuntimeError):
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
        if not rows:
            return None
        mention_id = rows[0]["id"]
        analysis_rows, risk_rows = await __import__("asyncio").gather(
            self.request("GET", "ai_analysis", params={"select": "mention_id", "mention_id": f"eq.{mention_id}", "limit": "1"}),
            self.request("GET", "risk_scores", params={"select": "mention_id", "mention_id": f"eq.{mention_id}", "limit": "1"}),
        )
        # A previous request may have inserted the mention before a later table
        # failed. Returning None lets the pipeline repair that partial record.
        return await self.get_processed(mention_id) if analysis_rows and risk_rows else None

    async def external_item_is_complete(self, business_id: UUID, source: str, external_id: str) -> bool:
        rows = await self.request("GET", "mentions", params={
            "select": "id", "business_id": f"eq.{business_id}", "source": f"ilike.{source}",
            "external_id": f"eq.{external_id}", "limit": "1",
        })
        if not rows:
            return False
        mention_id = rows[0]["id"]
        analysis_rows, risk_rows = await __import__("asyncio").gather(
            self.request("GET", "ai_analysis", params={"select": "mention_id", "mention_id": f"eq.{mention_id}", "limit": "1"}),
            self.request("GET", "risk_scores", params={"select": "mention_id", "mention_id": f"eq.{mention_id}", "limit": "1"}),
        )
        return bool(analysis_rows and risk_rows)

    async def count_mentions(self, business_id: UUID, source: str) -> int:
        rows = await self.request("GET", "mentions", params={
            "select": "id",
            "business_id": f"eq.{business_id}",
            "source": f"ilike.{source}",
            "limit": "10000",
        })
        return len(rows or [])

    async def persist_processed(self, result: ProcessedMention, provider: str = "local") -> ProcessedMention:
        m = result.mention
        existing_rows = await self.request("GET", "mentions", params={"select": "*", "business_id": f"eq.{m.business_id}", "content_hash": f"eq.{m.content_hash}", "limit": "1"})
        if existing_rows:
            mention_id = existing_rows[0]["id"]
            analysis_rows, risk_rows = await __import__("asyncio").gather(
                self.request("GET", "ai_analysis", params={"select": "mention_id", "mention_id": f"eq.{mention_id}", "limit": "1"}),
                self.request("GET", "risk_scores", params={"select": "mention_id", "mention_id": f"eq.{mention_id}", "limit": "1"}),
            )
            if analysis_rows and risk_rows:
                existing = await self._hydrate(existing_rows[0])
                return existing.model_copy(update={"duplicate": True})
        else:
            mention_payload = {
                "id": str(m.id), "business_id": str(m.business_id), "source": m.source,
                "source_type": m.source_type.value, "external_id": m.external_id,
                "external_url": m.external_url, "author_name": m.author_name, "text": m.text,
                "rating": m.rating, "published_at": m.published_at.isoformat() if m.published_at else None,
                "collected_at": m.collected_at.isoformat(), "language": result.analysis.language,
                "content_hash": m.content_hash, "metadata": m.metadata,
                "content_type": m.content_type.value, "author_type": m.author_type.value,
                "include_in_analysis": m.include_in_analysis, "reply_draft": m.reply_draft,
                "reply_generated_at": m.reply_generated_at.isoformat() if m.reply_generated_at else None,
                "reply_status": m.reply_status.value,
            }
            try:
                mention_rows = await self.request("POST", "mentions", json=mention_payload, prefer="return=representation")
            except RepositoryUnavailable as exc:
                if not any(column in str(exc) for column in ("content_type", "author_type", "include_in_analysis", "reply_draft", "reply_generated_at", "reply_status")):
                    raise
                for column in ("content_type", "author_type", "include_in_analysis", "reply_draft", "reply_generated_at", "reply_status"):
                    mention_payload.pop(column, None)
                mention_rows = await self.request("POST", "mentions", json=mention_payload, prefer="return=representation")
            mention_id = mention_rows[0]["id"]
        analysis_payload = {
            "mention_id": mention_id, "language": result.analysis.language,
            "sentiment": result.analysis.sentiment, "sentiment_score": result.analysis.sentiment_score,
            "severity": result.analysis.severity, "confidence": result.analysis.confidence,
            "summary": result.analysis.summary,
            "model": provider, "escalated": result.analysis.escalated,
        }
        try:
            await self.request("POST", "ai_analysis", params={"on_conflict": "mention_id"}, json=analysis_payload, prefer="resolution=merge-duplicates")
        except RepositoryUnavailable as exc:
            if "'summary' column" not in str(exc):
                raise
            analysis_payload.pop("summary", None)
            await self.request("POST", "ai_analysis", params={"on_conflict": "mention_id"}, json=analysis_payload, prefer="resolution=merge-duplicates")
        await self.request("DELETE", "mention_aspects", params={"mention_id": f"eq.{mention_id}"})
        if result.analysis.aspects:
            await self.request("POST", "mention_aspects", json=[{"mention_id": mention_id, "aspect": a.aspect, "sentiment": a.sentiment} for a in result.analysis.aspects])
        await self.request("POST", "risk_scores", params={"on_conflict": "mention_id"}, json={"mention_id": mention_id, "score": result.risk.score, "level": result.risk.level, "reasons": result.risk.reasons}, prefer="resolution=merge-duplicates")
        if result.alert_created:
            alert_rows = await self.request("GET", "alerts", params={"select": "id", "mention_id": f"eq.{mention_id}", "limit": "1"})
            if not alert_rows:
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

    async def author_is_ignored(self, business_id: UUID, source: str, author_key: str) -> bool:
        rows = await self.request("GET", "ignored_authors", params={"select": "id", "business_id": f"eq.{business_id}", "source": f"eq.{source}", "author_key": f"eq.{author_key}", "limit": "1"})
        return bool(rows)

    async def set_author_ignored(self, business_id: UUID, source: str, author_key: str, ignored: bool) -> None:
        match = {"business_id": f"eq.{business_id}", "source": f"eq.{source}", "author_key": f"eq.{author_key}"}
        if ignored:
            await self.request("POST", "ignored_authors", params={"on_conflict": "business_id,source,author_key"}, json={"business_id": str(business_id), "source": source, "author_key": author_key}, prefer="resolution=ignore-duplicates")
        else:
            await self.request("DELETE", "ignored_authors", params=match)
        await self.request("PATCH", "mentions", params={"business_id": f"eq.{business_id}", "source": f"eq.{source}", "metadata->>author_key": f"eq.{author_key}"}, json={"include_in_analysis": not ignored})

    async def get_recommendation(self, business_id: UUID, period_start: str, period_end: str) -> dict[str, Any] | None:
        rows = await self.request("GET", "business_recommendations", params={"select": "*", "business_id": f"eq.{business_id}", "period_start": f"eq.{period_start}", "period_end": f"eq.{period_end}", "limit": "1"})
        return rows[0] if rows else None

    async def save_recommendation(self, business_id: UUID, period_start: str, period_end: str, payload: dict[str, Any]) -> dict[str, Any]:
        rows = await self.request("POST", "business_recommendations", params={"on_conflict": "business_id,period_start,period_end"}, json={"business_id": str(business_id), "period_start": period_start, "period_end": period_end, "score": payload["score"], "summary": payload["summary"], "recommendations": payload["recommendations"]}, prefer="resolution=merge-duplicates,return=representation")
        return rows[0]

    async def _hydrate(self, row: dict[str, Any]) -> ProcessedMention:
        mention_id = row["id"]
        analysis_rows, aspect_rows, risk_rows, alert_rows = await __import__("asyncio").gather(
            self.request("GET", "ai_analysis", params={"select": "*", "mention_id": f"eq.{mention_id}", "limit": "1"}),
            self.request("GET", "mention_aspects", params={"select": "*", "mention_id": f"eq.{mention_id}"}),
            self.request("GET", "risk_scores", params={"select": "*", "mention_id": f"eq.{mention_id}", "limit": "1"}),
            self.request("GET", "alerts", params={"select": "id", "mention_id": f"eq.{mention_id}", "limit": "1"}),
        )
        analysis = analysis_rows[0] if analysis_rows else {"language": row.get("language") or "unknown", "sentiment": "neutral", "summary": "", "sentiment_score": 0, "severity": "low", "confidence": 0, "escalated": False}
        risk = risk_rows[0] if risk_rows else {"score": 0, "level": "low", "reasons": []}
        mention = NormalizedMention(**{k: row[k] for k in NormalizedMention.model_fields if k in row and row[k] is not None})
        return ProcessedMention(
            mention=mention,
            analysis=AIAnalysis(language=analysis["language"], sentiment=analysis["sentiment"], summary=analysis.get("summary") or "", sentiment_score=float(analysis.get("sentiment_score") or 0), severity=analysis["severity"], confidence=float(analysis.get("confidence") or 0), escalated=analysis.get("escalated", False), aspects=[Aspect(aspect=a["aspect"], sentiment=a["sentiment"]) for a in aspect_rows]),
            risk=RiskResult(score=risk["score"], level=risk["level"], reasons=risk.get("reasons") or []),
            alert_created=bool(alert_rows),
        )

    async def create_source(self, source: SourceCreate) -> dict[str, Any]:
        existing_params = {
            "select": "*",
            "business_id": f"eq.{source.business_id}",
            "source": f"eq.{source.source}",
            "connection_type": f"eq.{source.connection_type.value}",
            "collection_mode": f"eq.{source.collection_mode.value}",
            "source_url": f"eq.{source.source_url}" if source.source_url else "is.null",
            "limit": "1",
        }
        existing = await self.request("GET", "source_connections", params=existing_params)
        if existing:
            raise SourceAlreadyConnected(f"{source.source} is already connected to this workspace")
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

    async def upsert_source_credential(self, *, source_id: str, business_id: UUID, provider: str, encrypted_token: str, expires_at: datetime | None) -> dict[str, Any]:
        rows = await self.request(
            "POST",
            "source_credentials",
            params={"on_conflict": "source_connection_id"},
            json={
                "source_connection_id": source_id,
                "business_id": str(business_id),
                "provider": provider,
                "encrypted_token": encrypted_token,
                "expires_at": expires_at.isoformat() if expires_at else None,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            prefer="resolution=merge-duplicates,return=representation",
        )
        return rows[0]

    async def get_source_credential(self, *, source_id: str, business_id: UUID) -> dict[str, Any] | None:
        rows = await self.request(
            "GET",
            "source_credentials",
            params={
                "select": "source_connection_id,business_id,provider,encrypted_token,expires_at,updated_at",
                "source_connection_id": f"eq.{source_id}",
                "business_id": f"eq.{business_id}",
                "limit": "1",
            },
        )
        return rows[0] if rows else None

    async def delete_source_credential(self, *, source_id: str, business_id: UUID) -> None:
        await self.request(
            "DELETE",
            "source_credentials",
            params={"source_connection_id": f"eq.{source_id}", "business_id": f"eq.{business_id}"},
        )

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
