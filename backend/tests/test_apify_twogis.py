import asyncio
from uuid import uuid4
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from app.connectors.apify_twogis import ApifyTwoGisConnector
from app.models import MentionType, RawItem
from app.main import process_item


def test_apify_twogis_connector_mapping(monkeypatch):
    monkeypatch.setenv("APIFY_API_TOKEN", "dummy_token")

    connector = ApifyTwoGisConnector("https://2gis.kz/almaty/firm/70000001042393451/tab/reviews", "test-biz")

    mock_rows = [
        {
            "reviewId": "rev-12345",
            "rating": 5,
            "text": "Отличный университет! Прекрасные аудитории.",
            "dateCreated": "2026-06-26T14:54:53.028057+07:00",
            "authorName": "Алиса С.",
            "officialAnswer": {"text": "Спасибо за отзыв!", "date": "2026-06-27T10:00:00+07:00"},
            "placeId": "70000001042393451",
            "placeRating": 4.9,
            "placeReviewCount": 986,
        },
        {
            "reviewId": "rev-67890",
            "rating": 4,
            "text": "Хороший вуз, но парковка маловата.",
            "dateCreated": "2026-05-10T12:00:00.000000+07:00",
            "authorName": "Данияр",
        }
    ]

    class MockResponse:
        status_code = 201
        def json(self):
            return mock_rows

    async def run():
        with patch("httpx.AsyncClient.post", AsyncMock(return_value=MockResponse())):
            items = await connector.fetch_latest()
            assert len(items) == 2

            item1 = items[0]
            assert item1.source == "2gis"
            assert item1.source_type == MentionType.review
            assert item1.external_id == "rev-12345"
            assert item1.author_name == "Алиса С."
            assert item1.rating == 5.0
            assert item1.text == "Отличный университет! Прекрасные аудитории."
            assert isinstance(item1.published_at, datetime)
            assert item1.metadata["collected_by"] == "apify"
            assert item1.metadata["official_answer"]["text"] == "Спасибо за отзыв!"

    asyncio.run(run())


def test_apify_twogis_end_to_end_dedupe(monkeypatch):
    async def run():
        monkeypatch.setenv("APIFY_API_TOKEN", "dummy_token")
        biz_id = uuid4()

        raw1 = RawItem(
            source="2gis",
            source_type=MentionType.review,
            external_id="rev-999",
            author_name="Гульнара",
            text="Замечательное место для учебы!",
            rating=5.0,
        )

        res1 = await process_item(biz_id, raw1)
        assert res1.duplicate is False or res1.duplicate is None

        # Second sync of exact same item
        res2 = await process_item(biz_id, raw1)
        assert res2.duplicate is True

    asyncio.run(run())
