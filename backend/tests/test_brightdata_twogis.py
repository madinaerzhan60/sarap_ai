import os
import sys
import asyncio
import pytest
import httpx
# Ensure the backend directory is on the import path for the 'app' package
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.connectors.brightdata_twogis import BrightDataTwoGisConnector
from app.collectors.registry import collector_registry
from app.scrapers.fallback import ProviderNotConfigured, ProviderError
from app.models import RawItem
from app.scrapers.fallback import ProviderNotConfigured, ProviderError
from app.models import RawItem

# Helper mock response
class MockResponse:
    def __init__(self, status_code=200, text="", headers=None):
        self.status_code = status_code
        self._text = text
        self.headers = headers or {}

    async def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=self)

    @property
    def text(self):
        return self._text

# Dummy AsyncClient to capture request details
class DummyClient:
    def __init__(self, *args, **kwargs):
        self.headers = kwargs.get("headers", {})
        self.timeout = kwargs.get("timeout")
        self.follow_redirects = kwargs.get("follow_redirects")

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        pass

    async def get(self, endpoint, params=None):
        DummyClient.last_endpoint = endpoint
        DummyClient.last_params = params
        DummyClient.last_headers = self.headers
        # Return a successful HTML with a single review in JSON‑LD
        html = """
        <script type=\"application/ld+json\">
        {\"@type\":\"Review\",\"reviewBody\":\"Great place!\",\"author\":{\"name\":\"John Doe\"},\"reviewRating\":{\"ratingValue\":5},\"datePublished\":\"2023-01-01\"}
        </script>
        """
        return MockResponse(status_code=200, text=html, headers={"content-type": "text/html"})

@pytest.fixture(autouse=True)
def patch_httpx(monkeypatch):
    # Patch AsyncClient globally for the duration of tests
    monkeypatch.setattr(httpx, "AsyncClient", DummyClient)
    yield
    DummyClient.last_endpoint = None
    DummyClient.last_params = None
    DummyClient.last_headers = None

def test_provider_selection_brightdata(monkeypatch):
    monkeypatch.setenv("TWOGIS_PROVIDER", "brightdata")
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "dummy_key")
    monkeypatch.setenv("BRIGHTDATA_UNLOCKER_ZONE", "us")
    source = {"source": "2gis", "source_url": "https://2gis.example.com/firm/12345"}
    source_type, connector = collector_registry.resolve(source)
    assert source_type.value == "2gis"
    assert isinstance(connector, BrightDataTwoGisConnector)
    # Trigger request to capture details
    asyncio.run(connector.fetch_latest())
    assert DummyClient.last_endpoint == "https://api.brightdata.com/request"
    assert DummyClient.last_params["url"] == connector.page_url
    assert DummyClient.last_params["zone"] == "us"
    assert DummyClient.last_headers["Authorization"] == "Bearer dummy_key"

def test_missing_api_key(monkeypatch):
    monkeypatch.setenv("TWOGIS_PROVIDER", "brightdata")
    monkeypatch.delenv("BRIGHTDATA_API_KEY", raising=False)
    monkeypatch.setenv("BRIGHTDATA_UNLOCKER_ZONE", "us")
    source = {"source": "2gis", "source_url": "https://2gis.example.com/firm/12345"}
    _, connector = collector_registry.resolve(source)
    with pytest.raises(ProviderNotConfigured):
        asyncio.run(connector.fetch_latest())

def test_missing_zone(monkeypatch):
    monkeypatch.setenv("TWOGIS_PROVIDER", "brightdata")
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "dummy_key")
    monkeypatch.delenv("BRIGHTDATA_UNLOCKER_ZONE", raising=False)
    source = {"source": "2gis", "source_url": "https://2gis.example.com/firm/12345"}
    _, connector = collector_registry.resolve(source)
    with pytest.raises(ProviderNotConfigured):
        asyncio.run(connector.fetch_latest())

def test_successful_parsing(monkeypatch):
    monkeypatch.setenv("TWOGIS_PROVIDER", "brightdata")
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "dummy_key")
    monkeypatch.setenv("BRIGHTDATA_UNLOCKER_ZONE", "us")
    source = {"source": "2gis", "source_url": "https://2gis.example.com/firm/12345"}
    _, connector = collector_registry.resolve(source)
    items = asyncio.run(connector.fetch_latest())
    assert isinstance(items, list)
    assert len(items) == 1
    item = items[0]
    assert isinstance(item, RawItem)
    assert item.text == "Great place!"
    assert item.author_name == "John Doe"
    assert item.rating == 5

def test_direct_provider_still_works(monkeypatch):
    monkeypatch.setenv("TWOGIS_PROVIDER", "direct")
    # Ensure brightdata vars are present but should be ignored
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "dummy_key")
    monkeypatch.setenv("BRIGHTDATA_UNLOCKER_ZONE", "us")
    source = {"source": "2gis", "source_url": "https://2gis.example.com/firm/12345"}
    source_type, connector = collector_registry.resolve(source)
    from app.connectors.reviews import TwoGisPlaywrightConnector
    assert isinstance(connector, TwoGisPlaywrightConnector)

def test_non_2xx_response_raises_provider_error(monkeypatch):
    monkeypatch.setenv("TWOGIS_PROVIDER", "brightdata")
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "dummy_key")
    monkeypatch.setenv("BRIGHTDATA_UNLOCKER_ZONE", "us")
    class ErrorClient(DummyClient):
        async def get(self, endpoint, params=None):
            return MockResponse(status_code=403, text="", headers={"content-type": "text/html"})
    monkeypatch.setattr(httpx, "AsyncClient", ErrorClient)
    source = {"source": "2gis", "source_url": "https://2gis.example.com/firm/12345"}
    _, connector = collector_registry.resolve(source)
    with pytest.raises(ProviderError):
        asyncio.run(connector.fetch_latest())

