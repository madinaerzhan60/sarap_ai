import os
import pytest
import asyncio
from datetime import datetime

from app.collectors.registry import collector_registry, SourceType
from app.models import RawItem
from app.connectors import InstagramApifyConnector, FacebookApifyConnector

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
    source = {"source": "instagram", "source_url": "https://instagram.com/p/xyz"}
    source_type, connector = collector_registry.resolve(source)
    assert source_type == SourceType.INSTAGRAM
    assert isinstance(connector, InstagramApifyConnector)

    # Prepare dummy items with various dates
    items = [
        RawItem(source='instagram', source_type='social_comment', external_id='1', external_url='', author_name='A', text='old', rating=None, published_at='2024-01-01T00:00:00', metadata={}),
        RawItem(source='instagram', source_type='social_comment', external_id='2', external_url='', author_name='B', text='mid1', rating=None, published_at='2025-06-01T00:00:00', metadata={}),
        RawItem(source='instagram', source_type='social_comment', external_id='3', external_url='', author_name='C', text='mid2', rating=None, published_at='2026-05-01T00:00:00', metadata={}),
        RawItem(source='instagram', source_type='social_comment', external_id='4', external_url='', author_name='D', text='future', rating=None, published_at='2027-01-01T00:00:00', metadata={}),
    ]
    monkeypatch.setattr(DummyPipeline, 'items', items, raising=False)
    monkeypatch.setenv('INSTAGRAM_DATE_FROM', '2025-01-01')
    monkeypatch.setenv('INSTAGRAM_DATE_TO', '2026-12-31')
    fetched = asyncio.run(connector.fetch_latest())
    fetched_ids = {item.external_id for item in fetched}
    assert fetched_ids == {'2', '3'}

def test_facebook_apify_provider_selection_and_missing_token(monkeypatch):
    monkeypatch.setenv('FACEBOOK_PROVIDER', 'apify')
    source = {"source": "facebook", "source_url": "https://facebook.com/page"}
    source_type, connector = collector_registry.resolve(source)
    assert source_type == SourceType.FACEBOOK
    assert isinstance(connector, FacebookApifyConnector)

    monkeypatch.delenv('APIFY_TOKEN', raising=False)
    with pytest.raises(Exception) as excinfo:
        asyncio.run(connector.fetch_latest())
    from app.scrapers.fallback import ProviderNotConfigured
    assert isinstance(excinfo.value, ProviderNotConfigured)
