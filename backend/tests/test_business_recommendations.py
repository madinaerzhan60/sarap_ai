from uuid import uuid4

from app.main import _build_business_recommendations
from app.models import AIAnalysis, Aspect, ProcessedMention, RawItem, RiskResult
from app.services.normalization import normalize


def _item(text: str, sentiment: str, risk: int = 20, severity: str = "medium") -> ProcessedMention:
    mention = normalize(RawItem(source="2GIS", external_id=str(uuid4()), text=text), uuid4())
    analysis = AIAnalysis(
        language="ru",
        sentiment=sentiment,
        summary=text,
        sentiment_score=1 if sentiment == "positive" else -1,
        severity=severity,
        confidence=0.9,
        aspects=[Aspect(aspect="overall", sentiment=sentiment)],
    )
    return ProcessedMention(mention=mention, analysis=analysis, risk=RiskResult(score=risk, level="High" if risk >= 60 else "Medium", reasons=[]), alert_created=False)


def test_business_recommendations_are_specific_and_structured():
    rows = [
        _item("Приемная комиссия в общежитие грубая и ничего не объясняет", "negative", 72, "high"),
        _item("По общежитию приемная комиссия отвечает грубо и непонятно", "negative", 68, "high"),
        _item("Далеко в Каскелене, транспорт неудобный", "negative", 45),
        _item("Кампус красивый, клубы и студенческая атмосфера классные", "positive", 5),
        _item("Нравятся клубы, мероприятия и атмосфера кампуса", "positive", 4),
    ]

    payload = _build_business_recommendations(rows, "Restaurants & cafés")
    text = str(payload["recommendations"])

    assert "overall" not in text
    assert "delivery" not in text
    assert "Restaurants & cafés" not in payload["summary"]
    assert payload["main_strengths"][0]["topic"] == "campus_atmosphere"
    assert payload["main_weaknesses"][0]["topic"] in {"staff_communication", "dormitory"}
    assert payload["risk_signals"]

    urgent = payload["recommendations"]["urgent_fix"][0]
    assert set(urgent) == {"title", "evidence", "action", "count", "topic"}
    assert urgent["count"] == 2
    assert urgent["topic"] in {"staff_communication", "dormitory"}
    assert urgent["title"]
    assert urgent["evidence"]
    assert urgent["action"]


def test_urgent_fix_requires_repeated_or_high_risk_evidence():
    payload = _build_business_recommendations([
        _item("Далеко в Каскелене, транспорт неудобный", "negative", 35),
        _item("Автобус до кампуса неудобный, дорога занимает много времени", "negative", 30),
    ], "Education")

    assert payload["recommendations"]["urgent_fix"] == []
    assert payload["recommendations"]["improve"][0]["topic"] == "transport_access"
