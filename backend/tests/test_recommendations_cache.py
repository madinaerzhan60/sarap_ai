from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from app import main
from app.models import AIAnalysis, Aspect, ProcessedMention, RawItem, RiskResult
from app.services.normalization import normalize
from app.security import AuthContext


class FakeRecommendationRepository:
    configured = True

    def __init__(self) -> None:
        self.cached: dict | None = None
        self.saved_payloads: list[dict] = []
        self.items: list[ProcessedMention] = [
            _item("Кампус красивый, клубы и студенческая атмосфера классные", "positive"),
            _item("Нравятся клубы, мероприятия и атмосфера кампуса", "positive"),
        ]

    async def list_processed(self, business_id):
        return self.items

    async def request(self, method: str, path: str, *, params=None, json=None, prefer=None):
        if method == "GET" and path == "businesses":
            return [{"industry": "Education"}]
        raise AssertionError(f"Unexpected request {method} {path}")

    async def get_recommendation(self, business_id, period_start: str, period_end: str):
        return self.cached

    async def save_recommendation(self, business_id, period_start: str, period_end: str, payload: dict):
        self.saved_payloads.append(payload)
        self.cached = {
            "business_id": str(business_id),
            "period_start": period_start,
            "period_end": period_end,
            "score": payload["score"],
            "summary": payload["summary"],
            "recommendations": payload["recommendations"],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        return self.cached


def _item(text: str, sentiment: str) -> ProcessedMention:
    mention = normalize(RawItem(source="2GIS", external_id=str(uuid4()), text=text), uuid4())
    analysis = AIAnalysis(
        language="ru",
        sentiment=sentiment,
        summary=text,
        sentiment_score=1 if sentiment == "positive" else -1,
        severity="low" if sentiment == "positive" else "medium",
        confidence=0.9,
        aspects=[Aspect(aspect="campus_atmosphere", sentiment=sentiment)],
    )
    return ProcessedMention(mention=mention, analysis=analysis, risk=RiskResult(score=5, level="Low", reasons=[]), alert_created=False)


def _context() -> AuthContext:
    return AuthContext(user_id="user-1", access_token="token")


def _old_cached(business_id) -> dict:
    return {
        "business_id": str(business_id),
        "period_start": "2026-09-01",
        "period_end": "2026-09-30",
        "score": 0,
        "summary": "OLD SUMMARY",
        "recommendations": {"urgent_fix": [{"title": "OLD"}], "improve": [], "keep_doing": []},
        "generated_at": "2026-09-01T00:00:00+00:00",
    }


async def _allow_member(context, checked_id):
    return None


def test_refresh_true_returns_new_recommendation_not_old_cache(monkeypatch):
    business_id = uuid4()
    fake = FakeRecommendationRepository()
    fake.cached = _old_cached(business_id)
    monkeypatch.setattr(main, "repository", fake)
    monkeypatch.setattr(main, "require_business_member", _allow_member)

    result = asyncio.run(main.recommendations(business_id=business_id, refresh=True, context=_context()))

    assert result["summary"] != "OLD SUMMARY"
    assert result["recommendations"] != _old_cached(business_id)["recommendations"]
    assert result["summary"] == fake.saved_payloads[0]["summary"]


def test_old_cache_cannot_override_fresh_summary_or_recommendations(monkeypatch):
    business_id = uuid4()
    fake = FakeRecommendationRepository()
    fake.cached = _old_cached(business_id)
    monkeypatch.setattr(main, "repository", fake)
    monkeypatch.setattr(main, "require_business_member", _allow_member)

    result = asyncio.run(main.recommendations(business_id=business_id, refresh=True, context=_context()))

    assert "OLD" not in str(result)
    assert result["recommendations"]["keep_doing"]


def test_refresh_false_reuses_valid_cache(monkeypatch):
    business_id = uuid4()
    fake = FakeRecommendationRepository()
    fake.cached = _old_cached(business_id)
    monkeypatch.setattr(main, "repository", fake)
    monkeypatch.setattr(main, "require_business_member", _allow_member)

    result = asyncio.run(main.recommendations(business_id=business_id, refresh=False, context=_context()))

    assert result["summary"] == "OLD SUMMARY"
    assert fake.saved_payloads == []


def test_refreshed_result_is_persisted(monkeypatch):
    business_id = uuid4()
    fake = FakeRecommendationRepository()
    monkeypatch.setattr(main, "repository", fake)
    monkeypatch.setattr(main, "require_business_member", _allow_member)

    result = asyncio.run(main.recommendations(business_id=business_id, refresh=True, context=_context()))

    assert fake.saved_payloads
    assert fake.cached is not None
    assert fake.cached["summary"] == result["summary"]
    assert fake.cached["recommendations"] == result["recommendations"]


def test_next_request_receives_new_cached_result(monkeypatch):
    business_id = uuid4()
    fake = FakeRecommendationRepository()
    monkeypatch.setattr(main, "repository", fake)
    monkeypatch.setattr(main, "require_business_member", _allow_member)

    refreshed = asyncio.run(main.recommendations(business_id=business_id, refresh=True, context=_context()))
    cached = asyncio.run(main.recommendations(business_id=business_id, refresh=False, context=_context()))

    assert cached["summary"] == refreshed["summary"]
    assert cached["recommendations"] == refreshed["recommendations"]
    assert len(fake.saved_payloads) == 1
