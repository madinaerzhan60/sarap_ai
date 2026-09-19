from uuid import uuid4

from app.models import ExtractedReview, RawItem
from app.services.ai import analyze
from app.services.normalization import content_hash, normalize
from app.services.risk import calculate
from app.services.polling import next_poll
from app.connectors.reviews import ConnectorUnavailable, InstagramFallbackConnector, ModularScraperConnector, TwoGisPlaywrightConnector, connector_for, extract_reviews_from_html, extract_youtube_video_ids, youtube_video_id
from app.services.review_extraction import _plain_text_fallback, deduplicate_reviews, review_external_id
from app.scrapers.models import detect_language
from app.scrapers.fallback import ApifyProvider, CollectorProvider, FallbackPipeline, ProviderNotConfigured, normalize_api_item
from app.scrapers.models import ScrapedItem
import asyncio
import pytest
from app.services.telegram import business_from_token, connection_token


def test_mixed_language_aspects_and_risk():
    raw = RawItem(source="2gis", external_id="review-1", text="Кофе күшті, бірақ кассир қыз өте дөрекі екен.", rating=2)
    mention = normalize(raw, uuid4())
    result = analyze(mention.text)
    risk = calculate(mention, result)
    assert result.language == "mixed_kz_ru"
    assert {x.aspect for x in result.aspects} >= {"product", "staff"}
    assert risk.score >= 60


@pytest.mark.parametrize("text", [
    "круто",
    "Лучшее приложение для занятий спортом",
    "Мне нравится",
    "Самые выгодные цены",
    "Супер",
    "Ұнайды, ыңғайлы",
    "Спасибо 1Fit, очень довольна. Советую всем!",
])
def test_clear_positive_customer_language(text):
    assert analyze(text).sentiment == "positive"


@pytest.mark.parametrize("text", [
    "Пахнет подстановкой или обманом!",
    "Не могу зайти, служба поддержки не отвечает",
    "Не покупайте у них абонемент, никакой поддержки нет",
    "Если бы была возможность поставить оценку ниже, поставил бы",
    "Кейбір жерлерде қазақша қызмет етпейді!",
])
def test_clear_negative_customer_language(text):
    assert analyze(text).sentiment == "negative"


def test_numeric_rating_has_priority_for_sentiment():
    assert analyze("Текст без явных слов", 1).sentiment == "negative"
    assert analyze("Текст без явных слов", 3).sentiment == "neutral"
    assert analyze("Текст без явных слов", 5).sentiment == "positive"


def test_telegram_connection_token_is_signed(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "test-secret-that-is-long-enough-for-signing")
    business_id = str(uuid4())
    token = connection_token(business_id)
    assert business_from_token(token) == business_id
    assert business_from_token(token + "tampered") is None


def test_hash_is_stable_after_whitespace_normalization():
    a = RawItem(source="2gis", external_id="same", text="Great   coffee")
    b = RawItem(source="2GIS", external_id="same", text="Great coffee")
    assert content_hash(a) == content_hash(b)


def test_critical_keyword_increases_risk():
    raw = RawItem(source="web", external_id="critical-1", text="Подозрение на отравление после заказа.", rating=1)
    mention = normalize(raw, uuid4())
    risk = calculate(mention, analyze(mention.text))
    assert risk.level == "Critical"


def test_critical_polling_is_faster_than_low_activity():
    assert next_poll("low", critical_found=True) < next_poll("low")


def test_review_scraper_extracts_json_ld():
    html = '''<script type="application/ld+json">{
      "@type": "LocalBusiness",
      "review": [{"@type": "Review", "@id": "r-1", "reviewBody": "Очень долго ждали заказ", "author": {"name": "Aida"}, "reviewRating": {"ratingValue": "2"}, "datePublished": "2026-09-10"}]
    }</script>'''
    items = extract_reviews_from_html(html, "https://example.com/company", "example")
    assert len(items) == 1
    assert items[0].external_id == "r-1"
    assert items[0].author_name == "Aida"
    assert items[0].rating == 2
    assert items[0].metadata["collection_method"] == "scraper"


def test_extraction_engine_deduplicates_layout_copies():
    review = ExtractedReview(
        source_platform="2GIS",
        author_name="Aida",
        rating=2,
        estimated_sentiment="negative",
        language="ru",
        review_text="Очень долго ждали заказ",
        date_raw="2 недели назад",
        likes_count=0,
    )
    duplicate = review.model_copy(update={"review_text": "Очень   долго ждали заказ"})
    unique = deduplicate_reviews([review, duplicate])
    assert len(unique) == 1
    assert unique[0].publish_date is None
    assert unique[0].date_raw == "2 недели назад"


def test_extracted_review_id_is_stable():
    review = ExtractedReview(source_platform="Instagram", author_name="@aida", estimated_sentiment="positive", language="kk", review_text="Қызмет өте жақсы!", likes_count=4)
    assert review_external_id(review) == review_external_id(review.model_copy())


def test_plain_text_review_fallback_parses_ratings():
    reviews = _plain_text_fallback("Aida\nОчень долго ждали заказ — 2/5\nAliya\nКофе отличный и сервис быстрый — 5/5", None)
    assert len(reviews) == 2
    assert reviews[0].rating == 2
    assert reviews[0].author_name == "Aida"
    assert reviews[0].review_text == "Очень долго ждали заказ"
    assert reviews[0].estimated_sentiment == "negative"
    assert reviews[1].rating == 5
    assert reviews[1].author_name == "Aliya"
    assert reviews[1].estimated_sentiment == "positive"


def test_youtube_video_ids_are_deduplicated_in_page_order():
    html = '"videoId":"3GWEGzQLeWI" other "videoId":"WBzoKTkSCBo" duplicate "videoId":"3GWEGzQLeWI"'
    assert extract_youtube_video_ids(html) == ["3GWEGzQLeWI", "WBzoKTkSCBo"]


def test_youtube_video_url_variants_are_parsed():
    assert youtube_video_id("https://www.youtube.com/watch?v=3GWEGzQLeWI") == "3GWEGzQLeWI"
    assert youtube_video_id("https://youtu.be/3GWEGzQLeWI") == "3GWEGzQLeWI"
    assert youtube_video_id("https://www.youtube.com/shorts/3GWEGzQLeWI") == "3GWEGzQLeWI"
    assert youtube_video_id("https://www.youtube.com/@channel") is None


def test_collector_language_detection_handles_ru_kk_and_mixed_text():
    assert detect_language("Очень хороший сервис") == "ru"
    assert detect_language("Қызмет өте жақсы") == "kk"
    assert detect_language("Қызмет жақсы, но доставка медленная") == "mixed"


def test_twogis_search_url_is_normalized_to_reviews_tab():
    connector = TwoGisPlaywrightConnector("https://2gis.kz/almaty/search/1Fit/firm/70000001035980354/76.88%2C43.23")
    assert connector.page_url == "https://2gis.kz/almaty/firm/70000001035980354/tab/reviews"


def test_twogis_search_url_without_firm_id_is_rejected():
    with pytest.raises(ConnectorUnavailable, match="numeric company ID"):
        TwoGisPlaywrightConnector("https://2gis.kz/almaty/search/1Fit/firm/")


def test_twogis_source_rejects_non_twogis_domain():
    with pytest.raises(ConnectorUnavailable, match="2gis business page URL"):
        TwoGisPlaywrightConnector("https://example.com/almaty/firm/70000001035980354")


def test_instagram_source_uses_fallback_connector():
    connector = connector_for({"source": "Instagram", "collection_mode": "auto", "source_url": "https://www.instagram.com/p/example/"})
    assert isinstance(connector, InstagramFallbackConnector)


def test_instagram_profile_url_is_supported():
    connector = InstagramFallbackConnector("https://www.instagram.com/brand/")
    assert connector.is_profile is True


def test_instagram_system_route_is_rejected():
    with pytest.raises(ConnectorUnavailable, match="profile, post or reel"):
        InstagramFallbackConnector("https://www.instagram.com/explore/")


def test_yandex_source_uses_modular_playwright_connector():
    connector = connector_for({"source": "Yandex Maps", "collection_mode": "auto", "source_url": "https://yandex.kz/maps/org/example/123/reviews/"})
    assert isinstance(connector, ModularScraperConnector)


def test_sociavault_comment_is_normalized():
    item = normalize_api_item(
        {
            "id": "comment-7",
            "text": "Қызмет өте жақсы",
            "created_at": "2026-09-18T08:10:00.000Z",
            "user": {"username": "aida"},
        },
        "instagram",
        "https://instagram.com/p/example/",
        "sociavault",
    )
    assert item is not None
    assert item.author == "aida"
    assert item.external_id == "comment-7"
    assert item.collected_by == "sociavault"


def test_sociavault_youtube_comment_is_normalized():
    item = normalize_api_item(
        {
            "id": "yt-comment-1",
            "content": "Очень полезное видео",
            "publishedTime": "2026-09-18T08:10:00.000Z",
            "author": {"name": "@aida"},
            "engagement": {"likes": 7},
        },
        "youtube",
        "https://www.youtube.com/watch?v=3GWEGzQLeWI",
        "sociavault",
    )
    assert item is not None
    assert item.source == "YouTube"
    assert item.author == "@aida"
    assert item.metadata["likes_count"] == 7


def test_apify_2gis_review_is_normalized():
    item = normalize_api_item(
        {
            "id": "257144389",
            "rating": 5,
            "text": "Отличный сервис",
            "dateCreated": "2026-07-10T18:03:17+07:00",
            "likesCount": 3,
            "authorName": "Александра",
            "replyText": "Спасибо!",
        },
        "2gis",
        "https://2gis.kz/almaty/firm/1/tab/reviews",
        "apify",
    )
    assert item is not None
    assert item.source == "2GIS"
    assert item.author == "Александра"
    assert item.rating == 5
    assert item.metadata["business_reply"] == "Спасибо!"


def test_apify_2gis_sends_firm_id_and_filters_foreign_rows(monkeypatch):
    captured = {}

    class Response:
        status_code = 201
        def raise_for_status(self): return None
        def json(self):
            return [
                {"id": "wrong", "firmId": "4504127912651411", "text": "Отзыв про 2ГИС"},
                {"id": "right", "firmId": "70000001035980354", "text": "Отзыв про 1Fit"},
            ]

    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return None
        async def post(self, endpoint, *, params, json):
            captured.update(json)
            return Response()

    monkeypatch.setattr("app.scrapers.fallback.httpx.AsyncClient", Client)
    provider = ApifyProvider("2gis", "token", "getascraper/2gis-reviews-scraper")
    rows = asyncio.run(provider.collect("https://2gis.kz/almaty/firm/70000001035980354/tab/reviews", 10))
    assert captured["firmIds"] == ["70000001035980354"]
    assert captured["urls"] == []
    assert [row.text_content for row in rows] == ["Отзыв про 1Fit"]


def test_fallback_pipeline_uses_next_provider_after_empty_result():
    class EmptyProvider(CollectorProvider):
        name = "empty"
        platform = "instagram"

        async def collect(self, target_url: str, limit: int):
            return []

    class WorkingProvider(CollectorProvider):
        name = "working"
        platform = "instagram"

        async def collect(self, target_url: str, limit: int):
            return [ScrapedItem(source="Instagram", text_content="Хороший сервис", collected_by=self.name)]

    class MemoryStore:
        async def save(self, items, batch_size=250):
            return len(items)

    result = asyncio.run(FallbackPipeline("instagram", [EmptyProvider(), WorkingProvider()], MemoryStore()).collect_data("https://instagram.com/p/example/", 10))
    assert result["status"] == "ok"
    assert result["collected_by"] == "working"
    assert result["saved"] == 1


def test_playwright_provider_skips_browser_on_vercel(monkeypatch):
    from app.scrapers.fallback import PlaywrightProvider

    monkeypatch.setenv("VERCEL", "1")
    provider = PlaywrightProvider("2gis", lambda: None)
    with pytest.raises(ProviderNotConfigured, match="unavailable on Vercel"):
        asyncio.run(provider.collect("https://2gis.kz/almaty/firm/70000001035980354/tab/reviews", 10))
