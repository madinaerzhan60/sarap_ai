import asyncio
import os
import sys

import httpx
import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.collectors.registry import SourceType, collector_registry
from app.connectors.brightdata_twogis import BrightDataTwoGisConnector
from app.connectors.reviews import TwoGisPlaywrightConnector
from app.connectors.zenrows_twogis import ZenRowsTwoGisConnector
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

    def __init__(self, *args, **kwargs):
        self.timeout = kwargs.get("timeout")
        self.follow_redirects = kwargs.get("follow_redirects")

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get(self, endpoint, params=None):
        DummyZenRowsClient.last_endpoint = endpoint
        DummyZenRowsClient.last_params = params
        if DummyZenRowsClient.error:
            raise DummyZenRowsClient.error
        return DummyZenRowsClient.response


@pytest.fixture(autouse=True)
def reset_dummy_client(monkeypatch):
    DummyZenRowsClient.response = MockResponse(text=VALID_HTML)
    DummyZenRowsClient.error = None
    DummyZenRowsClient.last_endpoint = None
    DummyZenRowsClient.last_params = None
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
    connector = ZenRowsTwoGisConnector(TWOGIS_URL)

    asyncio.run(connector.fetch_latest())

    assert DummyZenRowsClient.last_endpoint == "https://api.zenrows.com/v1/"
    assert DummyZenRowsClient.last_params == {
        "url": connector.page_url,
        "apikey": "test-key",
        "js_render": "true",
        "premium_proxy": "true",
    }


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
        (MockResponse(status_code=200, text="<html>captcha</html>"), None),
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
