import asyncio
from uuid import uuid4

import pytest

from app.collectors.registry import CollectorRegistry
from app.connectors.search import DiscoveryNotConfigured, DiscoveryService
from app.models import RawItem
from app.scrapers.fallback import SociaVaultYouTubeProvider
from app.services.normalization import normalize
from app.services.topics import top_topics


def test_topics_remove_ru_fillers_aliases_and_merge_teacher_variants():
    result = dict(top_topics(["Чтобы просто этот крайне хороший преподаватель", "Преподы помогают студентам", "Преподаватели отвечают"], ["Хороший университет"]))
    assert result["Преподаватели"] == 3
    assert not {"Чтобы", "Просто", "Этот", "Крайне", "Хороший"} & result.keys()


def test_topics_support_kazakh_and_english_stopwords():
    result = dict(top_topics(["Осы өте жақсы оқытушы студенттер үшін", "The teachers are very helpful with students"] ))
    assert "Оқытушылар" in result
    assert "Teachers" in result
    assert not {"Осы", "Өте", "Үшін", "Very", "With"} & result.keys()


def test_normalization_prefers_stable_author_id_and_falls_back_to_name():
    business_id = uuid4()
    stable = normalize(RawItem(source="2gis", external_id="1", author_name="Jane", text="Good", metadata={"author_id": "user-7"}), business_id)
    fallback = normalize(RawItem(source="2gis", external_id="2", author_name="  JANE  DOE ", text="Good"), business_id)
    assert stable.metadata["author_key"] == "user-7"
    assert fallback.metadata["author_key"] == "jane doe"


def test_discovery_requires_an_explicit_provider(monkeypatch):
    for name in ("SEARXNG_URL", "TAVILY_API_KEY", "BRAVE_SEARCH_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(DiscoveryNotConfigured, match="Web discovery is not configured yet"):
        asyncio.run(DiscoveryService().search_many(["brand"]))


def test_paid_sociavault_is_disabled_without_global_opt_in(monkeypatch):
    monkeypatch.setenv("SOCIAVAULT_API_KEY", "configured")
    monkeypatch.setenv("ENABLE_SOCIAVAULT", "true")
    monkeypatch.setenv("ENABLE_PAID_FALLBACKS", "false")
    assert SociaVaultYouTubeProvider("configured").configured is False


def test_2gis_requires_external_worker(monkeypatch):
    monkeypatch.delenv("COLLECTOR_WORKER_URL", raising=False)
    monkeypatch.setenv("TWOGIS_PROVIDER", "worker")
    with pytest.raises(Exception, match="COLLECTOR_WORKER_URL"):
        CollectorRegistry().resolve({"source": "2gis", "source_url": "https://2gis.kz/almaty/firm/123/tab/reviews", "business_id": str(uuid4())})
