import asyncio
import json
import os
import sys

import httpx
import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.collectors.registry import SourceType, collector_registry
from app.main import _should_run_history_sync
from app.connectors.brightdata_twogis import BrightDataTwoGisConnector
from app.connectors.reviews import TwoGisPlaywrightConnector
from app.connectors import zenrows_twogis
from app.connectors.zenrows_twogis import ZenRowsTwoGisConnector, _looks_blocked
from app.models import RawItem
from app.scrapers.fallback import ProviderError, ProviderNotConfigured


TWOGIS_URL = "https://2gis.kz/almaty/firm/12345"
VALID_HTML = """
<html lang="ru">
<head><title>2GIS</title></head>
<body>
<script type="application/ld+json">
{
  "@type": "Review",
  "@id": "2gis-review-1",
  "reviewBody": "Great SDU service!",
  "author": {"name": "Aruzhan"},
  "reviewRating": {"ratingValue": 5},
  "datePublished": "2026-09-01"
}
</script>
</body>
</html>
"""
TWOGIS_CARD_HTML = """
<html lang="ru">
<head><title>Отзывы о SDU - 2ГИС</title></head>
<body>
  <div class="_1rowqpjv" data-review-id="review-42">
    <span title="Aruzhan">Aruzhan</span>
    <div class="_83kmcy"><a>Excellent university gym and campus life.</a></div>
    <span class="_10c0hgu">2026-09-01T00:00:00+00:00</span>
    <svg color="#ffb81c"></svg><svg color="#ffb81c"></svg><svg color="#ffb81c"></svg>
    <svg color="#ffb81c"></svg><svg color="#ffb81c"></svg>
  </div>
</body>
</html>
"""
TWOGIS_TWO_CARD_HTML = """
<html lang="ru">
<head><title>Отзывы о SDU - 2ГИС</title></head>
<body>
  <div class="_1rowqpjv" data-review-id="new-review">
    <span title="New Author">New Author</span>
    <div class="_83kmcy"><a>Fresh review loaded first.</a></div>
    <span class="_10c0hgu">2026-09-02T00:00:00+00:00</span>
    <svg color="#ffb81c"></svg><svg color="#ffb81c"></svg><svg color="#ffb81c"></svg>
  </div>
  <div class="_1rowqpjv" data-review-id="known-review">
    <span title="Known Author">Known Author</span>
    <div class="_83kmcy"><a>Known review that was already synced.</a></div>
    <span class="_10c0hgu">2026-09-01T00:00:00+00:00</span>
    <svg color="#ffb81c"></svg><svg color="#ffb81c"></svg>
  </div>
</body>
</html>
"""
TWOGIS_DUPLICATE_CARD_HTML = """
<html lang="ru">
<head><title>Отзывы о SDU - 2ГИС</title></head>
<body>
  <div data-sarap-accumulated-reviews="true">
    <div class="_1rowqpjv" data-review-id="dup-review">
      <span title="Aruzhan">Aruzhan</span>
      <div class="_83kmcy"><a>Same review only once.</a></div>
      <span class="_10c0hgu">2026-09-01T00:00:00+00:00</span>
      <svg color="#ffb81c"></svg>
    </div>
  </div>
  <div data-sarap-accumulated-reviews="true">
    <div class="_1rowqpjv" data-review-id="dup-review">
      <span title="Aruzhan">Aruzhan</span>
      <div class="_83kmcy"><a>Same review only once.</a></div>
      <span class="_10c0hgu">2026-09-01T00:00:00+00:00</span>
      <svg color="#ffb81c"></svg>
    </div>
  </div>
</body>
</html>
"""


class MockResponse:
    def __init__(self, status_code=200, text="", headers=None):
        self.status_code = status_code
        self._text = text
        self.headers = headers or {"content-type": "text/html"}
        self.request = httpx.Request("GET", "https://api.zenrows.com/v1/")

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=self.request, response=self)

    @property
    def text(self):
        return self._text


class DummyZenRowsClient:
    response = MockResponse()
    error = None
    last_endpoint = None
    last_params = None
    last_method = None
    last_timeout = None

    def __init__(self, *args, **kwargs):
        self.timeout = kwargs.get("timeout")
        self.follow_redirects = kwargs.get("follow_redirects")
        DummyZenRowsClient.last_timeout = self.timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get(self, endpoint, params=None):
        DummyZenRowsClient.last_endpoint = endpoint
        DummyZenRowsClient.last_params = params
        DummyZenRowsClient.last_method = "GET"
        if DummyZenRowsClient.error:
            raise DummyZenRowsClient.error
        return DummyZenRowsClient.response


class EmptyMessageHttpError(httpx.HTTPError):
    def __str__(self):
        return ""


@pytest.fixture(autouse=True)
def reset_dummy_client(monkeypatch):
    DummyZenRowsClient.response = MockResponse(text=VALID_HTML)
    DummyZenRowsClient.error = None
    DummyZenRowsClient.last_endpoint = None
    DummyZenRowsClient.last_params = None
    DummyZenRowsClient.last_method = None
    DummyZenRowsClient.last_timeout = None
    monkeypatch.setattr("app.connectors.zenrows_twogis.httpx.AsyncClient", DummyZenRowsClient)


def test_twogis_provider_zenrows_selects_zenrows_connector(monkeypatch):
    monkeypatch.setenv("TWOGIS_PROVIDER", "zenrows")
    source_type, connector = collector_registry.resolve({"source": "2gis", "source_url": TWOGIS_URL})

    assert source_type == SourceType.TWO_GIS
    assert isinstance(connector, ZenRowsTwoGisConnector)


def test_missing_zenrows_api_key_raises_provider_not_configured(monkeypatch):
    monkeypatch.setenv("TWOGIS_PROVIDER", "zenrows")
    monkeypatch.delenv("ZENROWS_API_KEY", raising=False)
    _, connector = collector_registry.resolve({"source": "2gis", "source_url": TWOGIS_URL})

    with pytest.raises(ProviderNotConfigured):
        asyncio.run(connector.fetch_latest())


def test_successful_zenrows_html_response_uses_expected_api_params(monkeypatch):
    monkeypatch.setenv("ZENROWS_API_KEY", "test-key")
    monkeypatch.setenv("TWOGIS_ZENROWS_SCROLLS", "5")
    connector = ZenRowsTwoGisConnector(TWOGIS_URL)

    asyncio.run(connector.fetch_latest())

    assert DummyZenRowsClient.last_method == "GET"
    assert DummyZenRowsClient.last_endpoint == "https://api.zenrows.com/v1/"
    assert DummyZenRowsClient.last_endpoint != "https://api.zenrows.com/v1/fetch"
    assert DummyZenRowsClient.last_params["url"] == connector.page_url
    assert DummyZenRowsClient.last_params["apikey"] == "test-key"
    assert DummyZenRowsClient.last_params["js_render"] == "true"
    assert DummyZenRowsClient.last_params["premium_proxy"] == "true"
    assert "js_instructions" in DummyZenRowsClient.last_params


def test_zenrows_uses_provider_specific_timeout(monkeypatch):
    monkeypatch.setenv("ZENROWS_API_KEY", "test-key")
    monkeypatch.setenv("CRAWLER_TIMEOUT_SECONDS", "20")
    monkeypatch.setenv("ZENROWS_TIMEOUT_SECONDS", "75")
    connector = ZenRowsTwoGisConnector(TWOGIS_URL)

    asyncio.run(connector.fetch_latest())

    assert DummyZenRowsClient.last_timeout == 75


def test_zenrows_request_contains_multiple_scrolls_in_one_api_call(monkeypatch):
    monkeypatch.setenv("ZENROWS_API_KEY", "test-key")
    monkeypatch.setenv("TWOGIS_ZENROWS_SCROLLS", "5")
    connector = ZenRowsTwoGisConnector(TWOGIS_URL)

    asyncio.run(connector.fetch_latest())

    instructions = json.loads(DummyZenRowsClient.last_params["js_instructions"])
    scroll_actions = [item for item in instructions if "evaluate" in item and "scrollIntoView" in item["evaluate"]]
    assert DummyZenRowsClient.last_endpoint == "https://api.zenrows.com/v1/"
    assert len(instructions) == 2
    assert len(scroll_actions) == 1
    assert "const scrollCount = 5" in scroll_actions[0]["evaluate"]
    assert DummyZenRowsClient.last_params["url"] == connector.page_url


def test_twogis_zenrows_scrolls_controls_scroll_count(monkeypatch):
    monkeypatch.setenv("ZENROWS_API_KEY", "test-key")
    monkeypatch.setenv("TWOGIS_ZENROWS_SCROLLS", "2")
    connector = ZenRowsTwoGisConnector(TWOGIS_URL)

    asyncio.run(connector.fetch_latest())

    instructions = json.loads(DummyZenRowsClient.last_params["js_instructions"])
    evaluate_actions = [item for item in instructions if "evaluate" in item]
    assert len(instructions) == 2
    assert len(evaluate_actions) == 1
    assert "const scrollCount = 2" in evaluate_actions[0]["evaluate"]


def test_backfill_scrolls_controls_scroll_count(monkeypatch):
    monkeypatch.setenv("ZENROWS_API_KEY", "test-key")
    monkeypatch.setenv("TWOGIS_ZENROWS_BACKFILL_SCROLLS", "7")
    connector = ZenRowsTwoGisConnector(TWOGIS_URL)

    asyncio.run(connector.fetch_latest(backfill=True))

    instructions = json.loads(DummyZenRowsClient.last_params["js_instructions"])
    evaluate_actions = [item for item in instructions if "evaluate" in item]
    assert len(instructions) == 2
    assert len(evaluate_actions) == 1
    assert "const scrollCount = 7" in evaluate_actions[0]["evaluate"]
    assert "const noGrowthLimit" in evaluate_actions[0]["evaluate"]
    assert "noGrowthIterations >= noGrowthLimit" in evaluate_actions[0]["evaluate"]
    assert "collectCurrentReviewCards" in evaluate_actions[0]["evaluate"]
    assert "data-sarap-accumulated-reviews" in evaluate_actions[0]["evaluate"]


def test_backfill_scrolls_40_generate_compact_query(monkeypatch):
    monkeypatch.setenv("ZENROWS_API_KEY", "test-key")
    monkeypatch.setenv("TWOGIS_ZENROWS_BACKFILL_SCROLLS", "40")
    connector = ZenRowsTwoGisConnector(TWOGIS_URL)

    asyncio.run(connector.fetch_latest(backfill=True))

    instructions = json.loads(DummyZenRowsClient.last_params["js_instructions"])
    evaluate_actions = [item for item in instructions if "evaluate" in item]
    assert len(instructions) == 2
    assert len(evaluate_actions) == 1
    assert "const scrollCount = 40" in evaluate_actions[0]["evaluate"]
    assert DummyZenRowsClient.last_params["js_instructions"].count("scrollIntoView") == 1
    assert DummyZenRowsClient.last_endpoint == "https://api.zenrows.com/v1/"
    assert "js_instructions" not in DummyZenRowsClient.last_endpoint


def test_backfill_scrolls_150_do_not_enlarge_request_url(monkeypatch):
    monkeypatch.setenv("ZENROWS_API_KEY", "test-key")
    monkeypatch.setenv("TWOGIS_ZENROWS_BACKFILL_SCROLLS", "150")
    connector = ZenRowsTwoGisConnector(TWOGIS_URL)

    asyncio.run(connector.fetch_latest(backfill=True))

    instructions = json.loads(DummyZenRowsClient.last_params["js_instructions"])
    evaluate_actions = [item for item in instructions if "evaluate" in item]
    assert DummyZenRowsClient.last_method == "GET"
    assert DummyZenRowsClient.last_endpoint == "https://api.zenrows.com/v1/"
    assert len(DummyZenRowsClient.last_endpoint) == len("https://api.zenrows.com/v1/")
    assert len(instructions) == 2
    assert len(evaluate_actions) == 1
    assert "const scrollCount = 150" in evaluate_actions[0]["evaluate"]


def test_compact_query_guard_returns_provider_error(monkeypatch):
    monkeypatch.setenv("ZENROWS_API_KEY", "test-key")
    monkeypatch.setenv("ZENROWS_MAX_QUERY_BYTES", "200")
    connector = ZenRowsTwoGisConnector(TWOGIS_URL)

    with pytest.raises(ProviderError, match="query_too_long"):
        asyncio.run(connector.fetch_latest(backfill=True))

    assert DummyZenRowsClient.last_endpoint is None


def test_backfill_completion_metadata_is_read_from_accumulator(monkeypatch):
    monkeypatch.setenv("ZENROWS_API_KEY", "test-key")
    DummyZenRowsClient.response = MockResponse(
        text="""
        <html><body>
          <div data-sarap-accumulated-reviews="true" data-sarap-history-complete="true" data-sarap-no-growth-iterations="8">
            <div class="_1rowqpjv" data-review-id="done-review">
              <span title="Aruzhan">Aruzhan</span>
              <div class="_83kmcy"><a>History item.</a></div>
              <span class="_10c0hgu">2026-09-01T00:00:00+00:00</span>
              <svg color="#ffb81c"></svg>
            </div>
          </div>
        </body></html>
        """
    )
    connector = ZenRowsTwoGisConnector(TWOGIS_URL)

    asyncio.run(connector.fetch_latest(backfill=True))

    assert connector.last_collection_metadata["history_complete"] is True
    assert connector.last_collection_metadata["no_growth_iterations"] == 8


def test_existing_2gis_parser_converts_zenrows_html_to_raw_items(monkeypatch):
    monkeypatch.setenv("ZENROWS_API_KEY", "test-key")
    connector = ZenRowsTwoGisConnector(TWOGIS_URL)

    items = asyncio.run(connector.fetch_latest())

    assert len(items) == 1
    assert isinstance(items[0], RawItem)
    assert items[0].source == "2gis"
    assert items[0].external_id == "2gis-review-1"
    assert items[0].text == "Great SDU service!"
    assert items[0].author_name == "Aruzhan"
    assert items[0].rating == 5


def test_rendered_2gis_review_cards_use_existing_dom_parser(monkeypatch):
    monkeypatch.setenv("ZENROWS_API_KEY", "test-key")
    DummyZenRowsClient.response = MockResponse(text=TWOGIS_CARD_HTML)
    connector = ZenRowsTwoGisConnector(TWOGIS_URL)

    items = asyncio.run(connector.fetch_latest())

    assert len(items) == 1
    assert items[0].source == "2gis"
    assert items[0].external_id
    assert items[0].text == "Excellent university gym and campus life."
    assert items[0].author_name == "Aruzhan"
    assert items[0].rating == 5


def test_normal_incremental_respects_last_seen_item_id(monkeypatch):
    monkeypatch.setenv("ZENROWS_API_KEY", "test-key")
    DummyZenRowsClient.response = MockResponse(text=TWOGIS_TWO_CARD_HTML)
    connector = ZenRowsTwoGisConnector(TWOGIS_URL)

    items = asyncio.run(connector.fetch_latest("known-review"))

    assert [item.external_id for item in items] == ["new-review"]


def test_backfill_ignores_last_seen_item_id(monkeypatch):
    monkeypatch.setenv("ZENROWS_API_KEY", "test-key")
    DummyZenRowsClient.response = MockResponse(text=TWOGIS_TWO_CARD_HTML)
    connector = ZenRowsTwoGisConnector(TWOGIS_URL)

    items = asyncio.run(connector.fetch_latest("known-review", backfill=True))

    assert [item.external_id for item in items] == ["new-review", "known-review"]


def test_normal_sync_auto_selects_history_when_2gis_count_is_low(monkeypatch):
    monkeypatch.setenv("TWOGIS_PROVIDER", "zenrows")
    monkeypatch.setenv("TWOGIS_HISTORY_SYNC_MIN_STORED", "200")
    monkeypatch.setattr("app.main._stored_source_count", lambda business_id, source_name: asyncio.sleep(0, result=97))

    should_backfill, stored_count = asyncio.run(_should_run_history_sync(
        {"source": "2GIS", "last_seen_item_id": "known-review"},
        "4831e885-e309-4d28-8311-6e54cfb29059",
        False,
    ))

    assert should_backfill is True
    assert stored_count == 97


def test_normal_sync_stays_incremental_after_history_threshold(monkeypatch):
    monkeypatch.setenv("TWOGIS_PROVIDER", "zenrows")
    monkeypatch.setenv("TWOGIS_HISTORY_SYNC_MIN_STORED", "200")
    monkeypatch.setattr("app.main._stored_source_count", lambda business_id, source_name: asyncio.sleep(0, result=900))

    should_backfill, stored_count = asyncio.run(_should_run_history_sync(
        {"source": "2GIS", "last_seen_item_id": "newest-review"},
        "4831e885-e309-4d28-8311-6e54cfb29059",
        False,
    ))

    assert should_backfill is False
    assert stored_count == 900


def test_normal_sync_stays_incremental_after_history_marker(monkeypatch):
    monkeypatch.setenv("TWOGIS_PROVIDER", "zenrows")
    monkeypatch.setenv("TWOGIS_HISTORY_SYNC_MIN_STORED", "200")
    monkeypatch.setattr("app.main._stored_source_count", lambda business_id, source_name: asyncio.sleep(0, result=40))

    should_backfill, stored_count = asyncio.run(_should_run_history_sync(
        {"source": "2GIS", "last_seen_published_at": "2026-09-26T00:00:00+00:00"},
        "4831e885-e309-4d28-8311-6e54cfb29059",
        False,
    ))

    assert should_backfill is False
    assert stored_count == 40


def test_duplicate_accumulated_cards_are_deduped(monkeypatch):
    monkeypatch.setenv("ZENROWS_API_KEY", "test-key")
    DummyZenRowsClient.response = MockResponse(text=TWOGIS_DUPLICATE_CARD_HTML)
    connector = ZenRowsTwoGisConnector(TWOGIS_URL)

    items = asyncio.run(connector.fetch_latest(backfill=True))

    assert [item.external_id for item in items] == ["dup-review"]


def test_backfill_still_uses_one_zenrows_http_request(monkeypatch):
    calls = 0

    class CountingClient(DummyZenRowsClient):
        async def get(self, endpoint, params=None):
            nonlocal calls
            calls += 1
            return await super().get(endpoint, params=params)

    monkeypatch.setenv("ZENROWS_API_KEY", "test-key")
    monkeypatch.setattr("app.connectors.zenrows_twogis.httpx.AsyncClient", CountingClient)
    connector = ZenRowsTwoGisConnector(TWOGIS_URL)

    asyncio.run(connector.fetch_latest(backfill=True))

    assert calls == 1


def test_zenrows_uses_backfill_specific_timeout(monkeypatch):
    monkeypatch.setenv("ZENROWS_API_KEY", "test-key")
    monkeypatch.setenv("ZENROWS_TIMEOUT_SECONDS", "20")
    monkeypatch.setenv("ZENROWS_BACKFILL_TIMEOUT_SECONDS", "180")
    connector = ZenRowsTwoGisConnector(TWOGIS_URL)

    asyncio.run(connector.fetch_latest(backfill=True))

    assert DummyZenRowsClient.last_timeout == 180


@pytest.mark.parametrize(
    "content_type",
    [
        "text/plain; charset=utf-8",
        "text/html; charset=utf-8",
    ],
)
def test_zenrows_accepts_valid_html_for_supported_content_types(monkeypatch, content_type):
    monkeypatch.setenv("ZENROWS_API_KEY", "test-key")
    DummyZenRowsClient.response = MockResponse(
        status_code=200,
        text=VALID_HTML,
        headers={"content-type": content_type},
    )
    connector = ZenRowsTwoGisConnector(TWOGIS_URL)

    items = asyncio.run(connector.fetch_latest())

    assert len(items) == 1
    assert items[0].external_id == "2gis-review-1"


def test_zenrows_rejects_text_plain_non_html_error(monkeypatch):
    monkeypatch.setenv("ZENROWS_API_KEY", "test-key")
    DummyZenRowsClient.response = MockResponse(
        status_code=200,
        text="upstream rendered response unavailable",
        headers={"content-type": "text/plain; charset=utf-8"},
    )
    connector = ZenRowsTwoGisConnector(TWOGIS_URL)

    with pytest.raises(ProviderError):
        asyncio.run(connector.fetch_latest())


@pytest.mark.parametrize(
    "response,error",
    [
        (MockResponse(status_code=403, text="denied"), None),
        (None, httpx.ConnectError("network failed")),
        (MockResponse(status_code=200, text=""), None),
    ],
)
def test_zenrows_failures_raise_provider_error(monkeypatch, response, error):
    monkeypatch.setenv("ZENROWS_API_KEY", "test-key")
    if response is not None:
        DummyZenRowsClient.response = response
    DummyZenRowsClient.error = error
    connector = ZenRowsTwoGisConnector(TWOGIS_URL)

    with pytest.raises(ProviderError):
        asyncio.run(connector.fetch_latest())


@pytest.mark.parametrize(
    "error,expected",
    [
        (httpx.ReadTimeout(""), "ReadTimeout"),
        (httpx.ConnectTimeout(""), "ConnectTimeout"),
        (EmptyMessageHttpError(""), "EmptyMessageHttpError"),
    ],
)
def test_zenrows_http_errors_include_useful_diagnostic(monkeypatch, error, expected):
    monkeypatch.setenv("ZENROWS_API_KEY", "test-key")
    DummyZenRowsClient.error = error
    connector = ZenRowsTwoGisConnector(TWOGIS_URL)

    with pytest.raises(ProviderError) as excinfo:
        asyncio.run(connector.fetch_latest())

    message = str(excinfo.value)
    assert message.startswith(f"zenrows: {expected} after ")
    assert message != "zenrows:"


def test_zenrows_real_captcha_html_is_blocked(monkeypatch):
    monkeypatch.setenv("ZENROWS_API_KEY", "test-key")
    DummyZenRowsClient.response = MockResponse(
        status_code=200,
        text="<html><body><h1>Captcha</h1><p>Verify you are human</p></body></html>",
        headers={"content-type": "text/html"},
    )
    connector = ZenRowsTwoGisConnector(TWOGIS_URL)

    with pytest.raises(ProviderError, match="blocked or captcha"):
        asyncio.run(connector.fetch_latest())


def test_normal_2gis_html_with_harmless_block_words_is_not_blocked():
    html = """
    <html>
      <head>
        <meta name="yandex-verification" content="abc">
        <script>
          window.__CONFIG__ = {
            captchaUrl: "https://captcha.2gis.ru/",
            cdn: "https://cdnjs.cloudflare.com/ajax/libs/example.js"
          };
        </script>
      </head>
      <body><h1>Отзывы о SDU Life Culture and Sport Center</h1></body>
    </html>
    """

    assert _looks_blocked(html) is False


def test_normal_html_with_reviews_continues_to_parser(monkeypatch):
    monkeypatch.setenv("ZENROWS_API_KEY", "test-key")
    DummyZenRowsClient.response = MockResponse(
        status_code=200,
        text=VALID_HTML,
        headers={"content-type": "text/plain; charset=utf-8"},
    )
    connector = ZenRowsTwoGisConnector(TWOGIS_URL)

    items = asyncio.run(connector.fetch_latest())

    assert len(items) == 1
    assert items[0].text == "Great SDU service!"


def test_html_after_scrolling_is_passed_to_existing_parser(monkeypatch):
    captured = {}

    def fake_parser(html, page_url, source):
        captured["html"] = html
        captured["page_url"] = page_url
        captured["source"] = source
        return [
            RawItem(
                source=source,
                source_type="review",
                external_id="parsed-after-scroll",
                external_url=page_url,
                text="Parsed after scroll",
                metadata={},
            )
        ]

    monkeypatch.setenv("ZENROWS_API_KEY", "test-key")
    monkeypatch.setattr(zenrows_twogis, "extract_reviews_from_html", fake_parser)
    DummyZenRowsClient.response = MockResponse(text="<html><body><div>rendered after scroll</div></body></html>")
    connector = ZenRowsTwoGisConnector(TWOGIS_URL)

    items = asyncio.run(connector.fetch_latest())

    assert captured["html"] == "<html><body><div>rendered after scroll</div></body></html>"
    assert captured["page_url"] == connector.page_url
    assert captured["source"] == "2gis"
    assert items[0].external_id == "parsed-after-scroll"


def test_parser_no_results_is_not_reported_as_blocked(monkeypatch):
    monkeypatch.setenv("ZENROWS_API_KEY", "test-key")
    DummyZenRowsClient.response = MockResponse(
        status_code=200,
        text="<html><body><h1>Отзывы о SDU Life Culture and Sport Center</h1></body></html>",
        headers={"content-type": "text/plain; charset=utf-8"},
    )
    connector = ZenRowsTwoGisConnector(TWOGIS_URL)

    with pytest.raises(ProviderError) as excinfo:
        asyncio.run(connector.fetch_latest())

    assert "no usable 2GIS reviews found" in str(excinfo.value)


def test_twogis_provider_brightdata_still_selects_brightdata(monkeypatch):
    monkeypatch.setenv("TWOGIS_PROVIDER", "brightdata")
    source_type, connector = collector_registry.resolve({"source": "2gis", "source_url": TWOGIS_URL})

    assert source_type == SourceType.TWO_GIS
    assert isinstance(connector, BrightDataTwoGisConnector)


def test_twogis_provider_direct_still_selects_direct_connector(monkeypatch):
    monkeypatch.setenv("TWOGIS_PROVIDER", "direct")
    source_type, connector = collector_registry.resolve({"source": "2gis", "source_url": TWOGIS_URL})

    assert source_type == SourceType.TWO_GIS
    assert isinstance(connector, TwoGisPlaywrightConnector)


def test_yandex_routing_remains_unchanged(monkeypatch):
    monkeypatch.setenv("TWOGIS_PROVIDER", "zenrows")
    monkeypatch.setenv("YANDEX_PROVIDER", "direct")
    source_type, connector = collector_registry.resolve(
        {"source": "Yandex Maps", "source_url": "https://yandex.kz/maps/org/example/123/reviews/"}
    )

    assert source_type == SourceType.YANDEX_MAPS
    assert connector.source == "yandex_maps"
