from uuid import uuid4
from unittest.mock import patch

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


def test_negative_mentions_never_appear_in_keep_doing():
    payload = _build_business_recommendations([
        _item("Общежитие грубая приемная комиссия ничего не объясняет", "negative", 70, "high"),
        _item("В общежитии сотрудники грубо отвечают студентам", "negative", 65, "high"),
    ], "Education")

    assert payload["recommendations"]["keep_doing"] == []
    assert all(item["topic"] != "dormitory" for item in payload["recommendations"]["keep_doing"])


def test_positive_mentions_never_appear_in_improve_or_urgent():
    payload = _build_business_recommendations([
        _item("Кампус красивый, атмосфера классная и клубы активные", "positive", 5),
        _item("Очень нравится кампус, клубы и студенческая атмосфера", "positive", 4),
    ], "Education")

    assert payload["recommendations"]["urgent_fix"] == []
    assert payload["recommendations"]["improve"] == []
    assert payload["recommendations"]["keep_doing"][0]["topic"] == "campus_atmosphere"


def test_recommendation_evidence_belongs_to_same_topic_and_count_matches_mentions():
    rows = [
        _item("Приемная комиссия в общежитие грубая и ничего не объясняет", "negative", 72, "high"),
        _item("По общежитию приемная комиссия отвечает грубо и непонятно", "negative", 68, "high"),
        _item("Автобус до кампуса неудобный и долго ехать", "negative", 40),
    ]

    payload = _build_business_recommendations(rows, "Education")

    urgent = payload["recommendations"]["urgent_fix"][0]
    assert urgent["count"] == 2
    assert urgent["topic"] == "staff_communication"
    assert "приемная комиссия" in urgent["evidence"].casefold()
    assert "автобус" not in urgent["evidence"].casefold()


def test_keep_doing_action_is_preservational():
    payload = _build_business_recommendations([
        _item("Кампус красивый, атмосфера классная и клубы активные", "positive", 5),
        _item("Очень нравится кампус, клубы и студенческая атмосфера", "positive", 4),
    ], "Education")

    action = payload["recommendations"]["keep_doing"][0]["action"].casefold()
    assert any(word in action for word in ("сохраня", "продолж", "поддерж"))
    assert not any(word in action for word in ("жалоб", "исправ", "разобрать", "проверить"))


def test_mismatched_generic_evidence_is_rejected():
    rows = [
        _item("Приемная комиссия в общежитие грубая и ничего не объясняет", "negative", 72, "high"),
        _item("По общежитию приемная комиссия отвечает грубо и непонятно", "negative", 68, "high"),
    ]

    with patch("app.main._evidence_for_bucket", return_value="Жалуется на долгое ожидание"):
        payload = _build_business_recommendations(rows, "Education")

    assert payload["recommendations"]["urgent_fix"] == []
