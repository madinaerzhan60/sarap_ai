import asyncio
import json
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.main import delete_source, import_jobs, import_source_data, source_import_job_status
from app.models import ImportFieldMapping, SourceImportRequest
from app.security import AuthContext


def _context():
    return AuthContext(user_id="demo", access_token="", demo=True)


def test_csv_import_maps_to_rawitem_and_preserves_date():
    async def run():
        biz_id = uuid4()
        request = SourceImportRequest(
            business_id=biz_id,
            ingestion_method="csv",
            platform="Instagram",
            filename="instagram.csv",
            csv_content="comment,username,stars,date,comment_id,url\nGreat service,@aida,,2026-09-01,ig-1,https://instagram.com/p/1\n",
        )
        result = await import_source_data(request, _context())

        item = result.items[0].mention
        assert result.total_read == 1
        assert result.inserted == 1
        assert item.source == "Instagram"
        assert item.text == "Great service"
        assert item.author_name == "@aida"
        assert item.rating is None
        assert item.published_at is not None and item.published_at.date().isoformat() == "2026-09-01"

    asyncio.run(run())


def test_json_array_import_and_custom_mapping():
    async def run():
        request = SourceImportRequest(
            business_id=uuid4(),
            ingestion_method="json",
            platform="Facebook",
            json_content=json.dumps([{"body": "Loved it", "user": "Dana", "post_id": "fb-1"}]),
            mapping=ImportFieldMapping(text="body", author="user", external_id="post_id"),
        )
        result = await import_source_data(request, _context())

        item = result.items[0].mention
        assert result.inserted == 1
        assert item.source == "Facebook"
        assert item.external_id == "fb-1"
        assert item.rating is None

    asyncio.run(run())


def test_json_reviews_container_import():
    async def run():
        request = SourceImportRequest(
            business_id=uuid4(),
            ingestion_method="json",
            platform="2GIS",
            json_content=json.dumps({"reviews": [{"review_text": "Топ", "review_id": "two-1"}]}),
        )
        result = await import_source_data(request, _context())

        assert result.total_read == 1
        assert result.items[0].mention.text == "Топ"
        assert result.items[0].mention.source == "2GIS"

    asyncio.run(run())


def test_duplicate_import_skipped_and_short_identical_ids_preserved():
    async def run():
        biz_id = uuid4()
        request = SourceImportRequest(
            business_id=biz_id,
            ingestion_method="csv",
            platform="2GIS",
            csv_content=f"text,external_id\n❤️,{biz_id}-111\n❤️,{biz_id}-222\n❤️,{biz_id}-111\n",
        )
        result = await import_source_data(request, _context())

        assert result.total_read == 3
        assert result.inserted == 2
        assert result.duplicates == 1
        assert [row.mention.external_id for row in result.items[:2]] == [f"{biz_id}-111", f"{biz_id}-222"]

    asyncio.run(run())


def test_manual_mention_goes_through_common_pipeline():
    async def run():
        request = SourceImportRequest(
            business_id=uuid4(),
            ingestion_method="manual",
            platform="YouTube",
            manual_item={"text": "Helpful video", "author": "@viewer", "external_id": "manual-yt-1"},
            mapping=ImportFieldMapping(text="text", author="author", external_id="external_id"),
            default_content_type="video_comment",
        )
        result = await import_source_data(request, _context())

        item = result.items[0].mention
        assert item.source == "YouTube"
        assert item.source_type == "video_comment"
        assert item.metadata["ingestion_method"] == "manual"

    asyncio.run(run())


def test_use_source_from_file_keeps_platform_separate_from_ingestion_method():
    async def run():
        request = SourceImportRequest(
            business_id=uuid4(),
            ingestion_method="csv",
            platform="Other",
            use_source_from_file=True,
            csv_content="text,source,external_id\nGreat,Yandex Maps,yx-1\n",
        )
        result = await import_source_data(request, _context())

        item = result.items[0].mention
        assert item.source == "Yandex Maps"
        assert item.metadata["ingestion_method"] == "csv"

    asyncio.run(run())


def test_invalid_json_rejected_cleanly():
    async def run():
        request = SourceImportRequest(
            business_id=uuid4(),
            ingestion_method="json",
            platform="Other",
            json_content="{bad",
        )
        with pytest.raises(HTTPException) as exc:
            await import_source_data(request, _context())
        assert exc.value.status_code == 422

    asyncio.run(run())


def test_delete_source_removes_linked_imported_mentions():
    async def run():
        request = SourceImportRequest(
            business_id=uuid4(),
            ingestion_method="csv",
            platform="2GIS",
            display_name="Delete import test",
            csv_content="text,external_id\nTemporary review,delete-source-1\n",
        )
        result = await import_source_data(request, _context())
        assert result.inserted == 1
        assert result.source is not None

        deleted = await delete_source(result.source["id"], _context())

        assert deleted["deleted"] is True
        assert deleted["deleted_mentions"] == 1

    asyncio.run(run())


def test_bootstrap_import_can_reuse_logical_source_id():
    async def run():
        first = SourceImportRequest(
            business_id=uuid4(),
            ingestion_method="json",
            platform="2GIS",
            display_name="2GIS — SDU University",
            json_content=json.dumps([{"text": "Existing review", "id": "boot-1"}]),
        )
        initial = await import_source_data(first, _context())
        source_id = initial.source["id"]

        second = SourceImportRequest(
            business_id=first.business_id,
            source_id=source_id,
            ingestion_method="json",
            platform="2GIS",
            source_url="https://2gis.kz/almaty/firm/70000001042393451/tab/reviews",
            enable_automatic_sync=True,
            json_content=json.dumps([{"text": "Existing review", "id": "boot-1"}, {"text": "New review", "id": "boot-2"}]),
        )
        followup = await import_source_data(second, _context())

        assert followup.source["id"] == source_id
        assert followup.source["source_url"] == "https://2gis.kz/almaty/firm/70000001042393451/tab/reviews"
        assert followup.inserted == 1
        assert followup.duplicates == 1
        assert {item.mention.metadata["source_connection_id"] for item in followup.items} == {source_id}

    asyncio.run(run())


def test_large_import_returns_202_and_processes_batches(monkeypatch):
    async def run():
        monkeypatch.setenv("SOURCE_IMPORT_SYNC_LIMIT", "10")
        rows = [{"text": f"Review {index}", "id": f"large-{index}"} for index in range(25)]
        request = SourceImportRequest(
            business_id=uuid4(),
            ingestion_method="json",
            platform="2GIS",
            display_name="Large bootstrap",
            json_content=json.dumps(rows),
        )
        response = await import_source_data(request, _context())

        assert response.status_code == 202
        body = json.loads(response.body)
        assert body["total_read"] == 25
        assert body["status"] in {"queued", "running"}

        for _ in range(50):
            await asyncio.sleep(0.01)
            status = await source_import_job_status(body["job_id"], _context())
            if status["status"] == "completed":
                break

        status = import_jobs[body["job_id"]]
        assert status["status"] == "completed"
        assert status["processed"] == 25
        assert status["inserted"] == 25

    asyncio.run(run())
