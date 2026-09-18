from uuid import uuid4

from app.models import ExtractedReview, RawItem
from app.services.ai import analyze
from app.services.normalization import content_hash, normalize
from app.services.risk import calculate
from app.services.polling import next_poll
from app.connectors.reviews import TwoGisPlaywrightConnector, extract_reviews_from_html, extract_youtube_video_ids
from app.services.review_extraction import _plain_text_fallback, deduplicate_reviews, review_external_id
from app.scrapers.models import detect_language
from app.scrapers.fallback import CollectorProvider, FallbackPipeline, normalize_api_item
from app.scrapers.models import ScrapedItem
import asyncio


def test_mixed_language_aspects_and_risk():
    raw = RawItem(source="2gis", external_id="review-1", text="Кофе күшті, бірақ кассир қыз өте дөрекі екен.", rating=2)
    mention = normalize(raw, uuid4())
    result = analyze(mention.text)
    risk = calculate(mention, result)
    assert result.language == "mixed_kz_ru"
    assert {x.aspect for x in result.aspects} >= {"product", "staff"}
    assert risk.score >= 60


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


def test_collector_language_detection_handles_ru_kk_and_mixed_text():
    assert detect_language("Очень хороший сервис") == "ru"
    assert detect_language("Қызмет өте жақсы") == "kk"
    assert detect_language("Қызмет жақсы, но доставка медленная") == "mixed"


def test_twogis_search_url_is_normalized_to_reviews_tab():
    connector = TwoGisPlaywrightConnector("https://2gis.kz/almaty/search/1Fit/firm/70000001035980354/76.88%2C43.23")
    assert connector.page_url == "https://2gis.kz/almaty/firm/70000001035980354/tab/reviews"


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
