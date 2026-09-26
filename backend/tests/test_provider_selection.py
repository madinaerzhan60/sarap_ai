import pytest
import asyncio
from datetime import datetime

from app.collectors.registry import collector_registry, SourceType
from app.models import MentionType
from app.connectors import InstagramApifyConnector, FacebookApifyConnector, YouTubeApifyConnector, YandexApifyConnector
from app.connectors.apify_twogis import ApifyTwoGisConnector
from app.connectors.discovery import PublicDiscoveryConnector
from app.connectors.reviews import MapFallbackConnector, YouTubePublicConnector
from app.scrapers.fallback import get_apify_token
from app.scrapers.models import ScrapedItem

# Helper dummy provider and pipeline
class DummyProvider:
    def __init__(self, *args, **kwargs):
        pass

class DummyPipeline:
    def __init__(self, *args, **kwargs):
        self.items = kwargs.get('items', [])

    async def collect_items(self, page_url, limit=500):
        # Return dummy items, provider name, empty failures
        return self.items, "apify", []

# Patch the ApifyProvider and FallbackPipeline in the connector modules
@pytest.fixture(autouse=True)
def patch_apify(monkeypatch):
    # Patch in both modules where they are imported
    monkeypatch.setattr('app.scrapers.fallback.ApifyProvider', DummyProvider, raising=False)
    monkeypatch.setattr('app.scrapers.fallback.FallbackPipeline', DummyPipeline, raising=False)
    yield

def test_instagram_apify_provider_selection(monkeypatch):
    monkeypatch.setenv('INSTAGRAM_PROVIDER', 'apify')
    monkeypatch.setenv('APIFY_API_TOKEN', 'api-token')
    monkeypatch.setenv('APIFY_INSTAGRAM_ACTOR_ID', 'instagram/actor')
    source = {"source": "instagram", "source_url": "https://instagram.com/p/xyz"}
    source_type, connector = collector_registry.resolve(source)
    assert source_type == SourceType.INSTAGRAM
    assert isinstance(connector, InstagramApifyConnector)

    # Prepare dummy items with various dates
    items = [
        ScrapedItem(source='Instagram', external_id='1', author='A', text_content='old', published_at=datetime.fromisoformat('2024-01-01T00:00:00'), url='https://instagram.com/p/xyz', collected_by='apify'),
        ScrapedItem(source='Instagram', external_id='2', author='B', text_content='mid1', published_at=datetime.fromisoformat('2025-06-01T00:00:00'), url='https://instagram.com/p/xyz', collected_by='apify'),
        ScrapedItem(source='Instagram', external_id='3', author='C', text_content='mid2', published_at=datetime.fromisoformat('2026-05-01T00:00:00'), url='https://instagram.com/p/xyz', collected_by='apify'),
        ScrapedItem(source='Instagram', external_id='4', author='D', text_content='future', published_at=datetime.fromisoformat('2027-01-01T00:00:00'), url='https://instagram.com/p/xyz', collected_by='apify'),
    ]
    monkeypatch.setattr(DummyPipeline, 'items', items, raising=False)
    monkeypatch.setenv('INSTAGRAM_DATE_FROM', '2025-01-01')
    monkeypatch.setenv('INSTAGRAM_DATE_TO', '2026-12-31')
    fetched = asyncio.run(connector.fetch_latest())
    fetched_ids = {item.external_id for item in fetched}
    assert fetched_ids == {'2', '3'}

def test_facebook_apify_provider_selection_with_explicit_actor(monkeypatch):
    monkeypatch.setenv('FACEBOOK_PROVIDER', 'apify')
    monkeypatch.setenv('APIFY_FACEBOOK_ACTOR_ID', 'facebook/actor')
    source = {"source": "facebook", "source_url": "https://facebook.com/page"}
    source_type, connector = collector_registry.resolve(source)
    assert source_type == SourceType.FACEBOOK
    assert isinstance(connector, FacebookApifyConnector)


def test_facebook_apify_accepts_api_token_alias(monkeypatch):
    monkeypatch.setenv('FACEBOOK_PROVIDER', 'apify')
    monkeypatch.delenv('APIFY_TOKEN', raising=False)
    monkeypatch.setenv('APIFY_API_TOKEN', 'api-token')
    monkeypatch.setenv('APIFY_FACEBOOK_ACTOR_ID', 'facebook/actor')
    source = {"source": "facebook", "source_url": "https://facebook.com/page"}
    _, connector = collector_registry.resolve(source)
    assert isinstance(connector, FacebookApifyConnector)


@pytest.mark.parametrize("env_name", ["APIFY_API_TOKEN", "APIFY_TOKEN", "APIFY_API_KEY"])
def test_apify_token_aliases(monkeypatch, env_name):
    for key in ["APIFY_API_TOKEN", "APIFY_TOKEN", "APIFY_API_KEY"]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv(env_name, "configured")
    assert get_apify_token() == "configured"


def test_social_sources_fallback_without_apify_actor(monkeypatch):
    monkeypatch.setenv("APIFY_API_TOKEN", "api-token")
    monkeypatch.delenv("APIFY_INSTAGRAM_ACTOR_ID", raising=False)
    monkeypatch.delenv("APIFY_FACEBOOK_ACTOR_ID", raising=False)
    _, instagram = collector_registry.resolve({"source": "instagram", "source_url": "https://instagram.com/p/xyz"})
    _, facebook = collector_registry.resolve({"source": "facebook", "source_url": "https://facebook.com/page"})
    assert isinstance(instagram, PublicDiscoveryConnector)
    assert isinstance(facebook, PublicDiscoveryConnector)


def test_youtube_apify_primary_then_direct_fallback(monkeypatch):
    source = {"source": "youtube", "source_url": "https://www.youtube.com/watch?v=abc12345678"}
    monkeypatch.setenv("APIFY_API_TOKEN", "api-token")
    monkeypatch.setenv("APIFY_YOUTUBE_ACTOR_ID", "youtube/actor")
    _, apify_connector = collector_registry.resolve(source)
    assert isinstance(apify_connector, YouTubeApifyConnector)

    monkeypatch.delenv("APIFY_YOUTUBE_ACTOR_ID", raising=False)
    _, direct_connector = collector_registry.resolve(source)
    assert isinstance(direct_connector, YouTubePublicConnector)


def test_yandex_apify_primary_then_map_fallback(monkeypatch):
    source = {"source": "Yandex Maps", "source_url": "https://yandex.kz/maps/org/example/123/reviews/"}
    monkeypatch.setenv("APIFY_API_TOKEN", "api-token")
    monkeypatch.setenv("APIFY_YANDEX_ACTOR_ID", "yandex/actor")
    _, apify_connector = collector_registry.resolve(source)
    assert isinstance(apify_connector, YandexApifyConnector)

    monkeypatch.delenv("APIFY_YANDEX_ACTOR_ID", raising=False)
    _, direct_connector = collector_registry.resolve(source)
    assert isinstance(direct_connector, MapFallbackConnector)


def test_youtube_apify_maps_comments_with_null_rating(monkeypatch):
    monkeypatch.setenv("APIFY_API_TOKEN", "api-token")
    monkeypatch.setenv("APIFY_YOUTUBE_ACTOR_ID", "youtube/actor")
    source = {"source": "youtube", "source_url": "https://www.youtube.com/watch?v=abc12345678"}
    _, connector = collector_registry.resolve(source)
    assert isinstance(connector, YouTubeApifyConnector)
    monkeypatch.setattr(DummyPipeline, 'items', [
        ScrapedItem(source="YouTube", external_id="comment-1", author="@aida", text_content="Nice video", rating=5, url=source["source_url"], collected_by="apify")
    ], raising=False)
    items = asyncio.run(connector.fetch_latest())
    assert items[0].external_id == "comment-1"
    assert items[0].source_type == MentionType.video_comment
    assert items[0].rating is None


def test_twogis_apify_accepts_legacy_actor_env(monkeypatch):
    monkeypatch.setenv("APIFY_API_TOKEN", "dummy_token")
    monkeypatch.delenv("APIFY_TWOGIS_ACTOR_ID", raising=False)
    monkeypatch.setenv("APIFY_2GIS_ACTOR_ID", "legacy/actor")
    connector = ApifyTwoGisConnector("https://2gis.kz/almaty/firm/70000001042393451/tab/reviews", "test-biz")

    class MockResponse:
        status_code = 201
        def json(self):
            return []

    async def run():
        async def fake_post(endpoint, *, params, json):
            assert "/acts/legacy~actor/" in endpoint
            return MockResponse()
        from unittest.mock import AsyncMock, patch
        with patch("httpx.AsyncClient.post", AsyncMock(side_effect=fake_post)):
            assert await connector.fetch_latest() == []

    asyncio.run(run())
