import asyncio
import pytest
from uuid import uuid4
from unittest.mock import AsyncMock

from app.models import RawItem, MentionType, ProcessedMention, AIAnalysis, RiskResult
from app.services.normalization import normalize, dedupe_key, normalize_text
from app.services.dedupe import is_near_duplicate, find_near_duplicate_group, MIN_LENGTH_FOR_NEAR_DEDUPE
from app.main import analytics, process_item, _visible_product_mentions, _should_run_history_sync
from app.connectors.search import DiscoveryService, FreeSearchProvider, SearchResult
from app.repository import SupabaseRepository
from app.security import AuthContext


def test_normalize_text_and_dedupe_key():
    text1 = "  Отличный университет! Преподаватели супер.  "
    text2 = "Отличный университет! Преподаватели супер."

    assert normalize_text(text1) == text2

    item1 = RawItem(
        source="2gis",
        source_type=MentionType.review,
        external_id="rev-1",
        author_name="Алиса",
        text=text1,
        rating=5.0,
    )
    item2 = RawItem(
        source="2gis",
        source_type=MentionType.review,
        external_id="rev-1",
        author_name="Алиса ",
        text=text2,
        rating=5.0,
    )

    biz_id = uuid4()
    m1 = normalize(item1, biz_id)
    m2 = normalize(item2, biz_id)

    assert m1.dedupe_key == m2.dedupe_key
    assert m1.content_hash == m2.content_hash


def test_near_duplicate_short_text_ignored():
    short_a = "Очень хороший университет"
    short_b = "Очень хороший университет!"

    assert not is_near_duplicate(short_a, short_b)


def test_near_duplicate_long_text_matched():
    long_a = (
        "СДУ это отличный университет в Каскелене. Здесь прекрасный преподавательский "
        "состав, современные аудитории, хорошая библиотека и большая столовая. Рекомендую поступать!"
    )
    long_b = (
        "СДУ - это отличный университет в городе Каскелен. Там прекрасный преподавательский "
        "состав, современные аудитории, хорошая библиотека и большая столовая. Рекомендую всем поступать!"
    )

    assert len(long_a) > MIN_LENGTH_FOR_NEAR_DEDUPE
    assert len(long_b) > MIN_LENGTH_FOR_NEAR_DEDUPE
    assert is_near_duplicate(long_a, long_b)


def test_find_near_duplicate_group():
    long_a = (
        "СДУ это отличный университет в Каскелене. Здесь прекрасный преподавательский "
        "состав, современные аудитории, хорошая библиотека и большая столовая. Рекомендую поступать!"
    )
    long_b = (
        "СДУ - это отличный университет в городе Каскелен. Там прекрасный преподавательский "
        "состав, современные аудитории, хорошая библиотека и большая столовая. Рекомендую всем поступать!"
    )

    cand_id = str(uuid4())
    candidates = [{"id": cand_id, "text": long_a}]

    match = find_near_duplicate_group(long_b, candidates)
    assert match is not None
    assert match["id"] == cand_id


def test_process_item_idempotency_end_to_end():
    async def run():
        biz_id = uuid4()
        raw = RawItem(
            source="2gis",
            source_type=MentionType.review,
            external_id="ext-100",
            author_name="Студент СДУ",
            text="Замечательный университет с хорошими преподавателями!",
            rating=5.0,
        )

        res1 = await process_item(biz_id, raw)
        assert res1.duplicate is False or res1.duplicate is None

        res2 = await process_item(biz_id, raw)
        assert res2.duplicate is True

    asyncio.run(run())


def test_changing_relative_date_does_not_create_duplicate_row():
    async def run():
        biz_id = uuid4()
        raw_day1 = RawItem(
            source="2gis",
            source_type=MentionType.review,
            external_id="stable-fallback-id",
            author_name="Асхат",
            text="Хороший вуз!",
            rating=5.0,
            metadata={"date_raw": "3 дня назад"},
        )
        raw_day3 = RawItem(
            source="2gis",
            source_type=MentionType.review,
            external_id="stable-fallback-id",
            author_name="Асхат",
            text="Хороший вуз!",
            rating=5.0,
            metadata={"date_raw": "5 дней назад"},
        )

        res1 = await process_item(biz_id, raw_day1)
        res2 = await process_item(biz_id, raw_day3)

        assert res1.mention.dedupe_key == res2.mention.dedupe_key
        assert res2.duplicate is True

    asyncio.run(run())


def test_analytics_excludes_duplicate_occurrences():
    biz_id = uuid4()
    item1 = RawItem(source="2gis", source_type=MentionType.review, external_id="1", author_name="A", text="Good", rating=5.0)
    m1 = normalize(item1, biz_id)
    m2 = m1.model_copy(update={"id": uuid4(), "is_duplicate": True})

    analysis = AIAnalysis(language="ru", sentiment="positive", summary="", sentiment_score=1.0, severity="low", confidence=0.9, escalated=False, aspects=[])
    risk = RiskResult(score=10, level="low", reasons=[])

    proc1 = ProcessedMention(mention=m1, analysis=analysis, risk=risk, alert_created=False)
    proc2 = ProcessedMention(mention=m2, analysis=analysis, risk=risk, alert_created=False)

    visible = _visible_product_mentions([proc1, proc2])
    assert len(visible) == 1
    assert visible[0].mention.id == m1.id


def test_persist_processed_serializes_uuid_duplicate_ids():
    async def run():
        biz_id = uuid4()
        canonical_id = uuid4()
        duplicate_group_id = uuid4()
        mention = normalize(
            RawItem(source="2gis", source_type=MentionType.review, external_id="uuid-1", author_name="A", text="Copied long review text " * 8, rating=5.0),
            biz_id,
        ).model_copy(update={"is_duplicate": True, "canonical_mention_id": canonical_id, "duplicate_group_id": duplicate_group_id})
        analysis = AIAnalysis(language="ru", sentiment="positive", summary="", sentiment_score=0.8, severity="low", confidence=0.9, escalated=False, aspects=[])
        result = ProcessedMention(mention=mention, analysis=analysis, risk=RiskResult(score=5, level="low", reasons=[]), alert_created=False)
        repo = SupabaseRepository()
        repo.url = "https://example.supabase.co"
        repo.key = "test"
        mention_payloads = []

        async def fake_request(method, path, *, params=None, json=None, prefer=None):
            if json is not None:
                __import__("json").dumps(json)
            if method == "GET" and path == "mentions":
                return []
            if method == "POST" and path == "mentions":
                mention_payloads.append(json)
                return [{"id": str(mention.id)}]
            return None

        repo.request = fake_request

        await repo.persist_processed(result)

        assert mention_payloads[0]["canonical_mention_id"] == str(canonical_id)
        assert mention_payloads[0]["duplicate_group_id"] == str(duplicate_group_id)

    asyncio.run(run())


def test_analytics_does_not_request_business_aliases(monkeypatch):
    async def run():
        from app import main

        biz_id = uuid4()
        monkeypatch.setattr(main.repository, "url", "https://example.supabase.co")
        monkeypatch.setattr(main.repository, "key", "test")
        monkeypatch.setattr(main.repository, "list_processed", AsyncMock(return_value=[]))

        async def fake_request(method, path, *, params=None, json=None, prefer=None):
            assert path == "businesses"
            assert params["select"] == "name"
            return [{"name": "SARAP"}]

        monkeypatch.setattr(main.repository, "request", fake_request)

        response = await analytics(biz_id, context=AuthContext(user_id="demo", access_token="", demo=True))

        assert response["total"] == 0

    asyncio.run(run())


def test_twogis_history_sync_does_not_stop_at_200_stored(monkeypatch):
    async def run():
        monkeypatch.setenv("TWOGIS_PROVIDER", "zenrows")
        source = {"source": "2gis", "last_seen_published_at": None}
        biz_id = uuid4()

        monkeypatch.setattr("app.main._stored_source_count", AsyncMock(return_value=250))

        should_sync, count = await _should_run_history_sync(source, biz_id, False)
        assert should_sync is True
        assert count == 250

    asyncio.run(run())


def test_web_search_provider_free_does_not_raise(monkeypatch):
    async def run():
        monkeypatch.delenv("SEARXNG_URL", raising=False)
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
        monkeypatch.setenv("WEB_SEARCH_PROVIDER", "free")

        provider = FreeSearchProvider()
        # Mock search method of providers to return empty list without network
        for p in provider.providers:
            p.search = AsyncMock(return_value=[])

        results, stats = await provider.search_many(["SDU University"])
        assert isinstance(results, list)

    asyncio.run(run())


def test_short_identical_reviews_from_different_external_ids_are_preserved():
    async def run():
        biz_id = uuid4()
        rev_a = RawItem(
            source="2gis",
            source_type=MentionType.review,
            external_id="111",
            author_name="User A",
            text="❤️",
            rating=5.0,
        )
        rev_b = RawItem(
            source="2gis",
            source_type=MentionType.review,
            external_id="222",
            author_name="User B",
            text="❤️",
            rating=5.0,
        )

        res_a = await process_item(biz_id, rev_a)
        res_b = await process_item(biz_id, rev_b)

        assert res_a.duplicate is False or res_a.duplicate is None
        assert res_b.duplicate is False or res_b.duplicate is None
        assert res_a.mention.dedupe_key != res_b.mention.dedupe_key

        # Re-ingestion of same review A must be detected as duplicate
        res_a_again = await process_item(biz_id, rev_a)
        assert res_a_again.duplicate is True

    asyncio.run(run())
