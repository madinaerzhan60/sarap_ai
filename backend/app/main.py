from __future__ import annotations

from pathlib import Path
import asyncio
import csv
import hashlib
import io
import hmac
import json
import logging
import os
import re
from collections import Counter
from datetime import datetime, time, timezone
from datetime import date, timedelta
from uuid import UUID

from fastapi import Body, Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from app.connectors.reviews import ConnectorUnavailable, normalize_twogis_business_url
from app.collectors.registry import collector_registry
from app.connectors.search import DiscoveryNotConfigured, DiscoveryService, canonical_url, fan_out
from app.models import DiscoveryRequest, ExtractedReview, ManualImportRequest, MentionType, MentionUpdate, ProcessedMention, RawItem, ReplyDraftRequest, ReplyStatus, ReviewExtractionRequest, ReviewImportRequest, RiskResult, SourceCreate, SourceOAuthCredential, SourceUpdate
from app.services.llm import analyze_with_cascade, generate_reply_draft
from app.services.normalization import normalize
from app.services.review_extraction import ReviewExtractionUnavailable, extract_reviews, review_external_id
from app.services.risk import calculate
from app.services.topics import top_topics
from app.services.telegram import business_from_token, connection_token, send_alert
from app.services.source_credentials import CredentialEncryptionError, SourceCredentialVault
from app.security import AuthContext, require_admin_context, require_business_member, require_user
from app.repository import RepositoryUnavailable, SourceAlreadyConnected, repository
from app.scrapers.browser_runtime import browser_diagnostics

app = FastAPI(title="SARAP API", version="0.2.0", description="Reputation intelligence platform for Kazakhstan and the CIS")
frontend_origins = {"http://localhost:5173", "http://127.0.0.1:5173"}
if os.getenv("FRONTEND_URL"):
    frontend_origins.add(os.environ["FRONTEND_URL"].rstrip("/"))
app.add_middleware(CORSMiddleware, allow_origins=sorted(frontend_origins), allow_methods=["*"], allow_headers=["*"], allow_credentials=True)

# Isolated fallback used only when the local demo runs without Supabase.
seen_hashes: set[str] = set()
processed: list[ProcessedMention] = []
sources: list[dict] = []
ignored_authors: set[tuple[UUID, str, str]] = set()
logger = logging.getLogger("sarap.discovery")


def _visible_product_mentions(items: list[ProcessedMention]) -> list[ProcessedMention]:
    """Hide legacy rows created when the old YouTube connector stored video titles."""
    return [
        item for item in items
        if not (
            item.mention.source.casefold() == "youtube"
            and item.mention.source_type == MentionType.social_post
            and item.mention.metadata.get("content_type") == "video"
            and item.mention.metadata.get("collection_method") == "public_page"
        )
    ]


def _history_threshold(source_name: str) -> int:
    if str(source_name).casefold().strip() in {"2gis", "2gis maps"}:
        raw = os.getenv("TWOGIS_HISTORY_SYNC_MIN_STORED", "200")
        try:
            return max(0, int(raw))
        except ValueError:
            return 200
    return 0


async def _stored_source_count(business_id: UUID, source_name: str) -> int:
    if repository.configured:
        return await repository.count_mentions(business_id, source_name)
    return sum(1 for item in processed if item.mention.business_id == business_id and item.mention.source.casefold() == source_name.casefold())


async def _should_run_history_sync(source: dict, business_id: UUID, explicit_backfill: bool) -> tuple[bool, int]:
    if explicit_backfill:
        return True, await _stored_source_count(business_id, str(source.get("source", "")))
    source_name = str(source.get("source", ""))
    threshold = _history_threshold(source_name)
    if threshold <= 0:
        return False, await _stored_source_count(business_id, source_name)
    provider = os.getenv("TWOGIS_PROVIDER", "direct").strip().lower()
    if source_name.casefold().strip() not in {"2gis", "2gis maps"} or provider != "zenrows":
        return False, await _stored_source_count(business_id, source_name)
    stored_count = await _stored_source_count(business_id, source_name)
    if source.get("last_seen_published_at") and stored_count > 0:
        return False, stored_count
    return stored_count < threshold, stored_count


async def process_item(business_id: UUID, item: RawItem) -> ProcessedMention:
    mention = normalize(item, business_id)
    author_key = str(mention.metadata.get("author_key") or "")
    if author_key and ((repository.configured and await repository.author_is_ignored(business_id, mention.source, author_key)) or (business_id, mention.source, author_key) in ignored_authors):
        mention = mention.model_copy(update={"include_in_analysis": False})
    if repository.configured:
        previous = await repository.find_by_hash(business_id, mention.content_hash)
        if previous:
            return previous.model_copy(update={"duplicate": True})
    elif mention.content_hash in seen_hashes:
        previous = next(x for x in processed if x.mention.content_hash == mention.content_hash)
        return previous.model_copy(update={"duplicate": True})
    analysis = await analyze_with_cascade(mention.text, mention.rating)
    risk = calculate(mention, analysis) if mention.include_in_analysis else RiskResult(score=0, level="Excluded", reasons=["Excluded from customer reputation analysis"])
    result = ProcessedMention(mention=mention, analysis=analysis, risk=risk, alert_created=mention.include_in_analysis and risk.score >= 60)
    if repository.configured:
        result = await repository.persist_processed(result, "groq-gemini-cascade")
    else:
        seen_hashes.add(mention.content_hash)
        processed.append(result)
    if result.alert_created:
        try:
            chat_id = None
            if repository.configured:
                rows = await repository.request("GET", "telegram_connections", params={"select": "encrypted_chat_id,enabled", "business_id": f"eq.{business_id}", "enabled": "eq.true", "limit": "1"})
                if rows:
                    chat_id = SourceCredentialVault().decrypt(rows[0]["encrypted_chat_id"], business_id=business_id, source_connection_id=business_id, provider="telegram").get("access_token")
            if chat_id:
                await asyncio.to_thread(send_alert, result, str(chat_id))
        except (OSError, CredentialEncryptionError, RepositoryUnavailable):
            pass
    return result


@app.get("/api/health")
def health() -> JSONResponse:
    accounts_ready = bool(os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_ANON_KEY"))
    return JSONResponse(
        {"status": "ok", "service": "sarap-api", "accounts": "connected" if accounts_ready else "setup_required"},
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/health/playwright")
def playwright_health() -> JSONResponse:
    """Safe deployment diagnostics; never returns credentials or proxy values."""
    details = browser_diagnostics()
    return JSONResponse(
        {"status": "ok" if details["chromium_path_available"] else "setup_required", **details},
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/public-config")
def public_config() -> JSONResponse:
    """Only browser-safe values. Never expose the service-role or provider keys."""
    return JSONResponse(
        {
            "SUPABASE_URL": os.getenv("SUPABASE_URL", ""),
            "SUPABASE_ANON_KEY": os.getenv("SUPABASE_ANON_KEY", ""),
            "AUTH_REDIRECT_URL": os.getenv("FRONTEND_URL") or os.getenv("APP_BASE_URL", ""),
            # Empty means same-origin. API_URL is only needed when the frontend and
            # backend are deployed on different domains.
            "API_URL": os.getenv("API_URL", ""),
        },
        headers={"Cache-Control": "no-store"},
    )


@app.post("/api/telegram/connect")
async def telegram_connect(business_id: UUID, context: AuthContext = Depends(require_user)) -> dict:
    await require_business_member(context, business_id)
    username = os.getenv("TELEGRAM_BOT_USERNAME", "sarap_ai_bot").lstrip("@")
    if not username:
        raise HTTPException(503, "Telegram bot is not configured yet")
    try:
        token = connection_token(str(business_id))
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    return {"url": f"https://t.me/{username}?start={token}"}


@app.post("/api/telegram/webhook")
async def telegram_webhook(update: dict = Body(...), x_telegram_bot_api_secret_token: str | None = Header(default=None)) -> dict:
    configured_secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
    expected = hashlib.sha256(configured_secret.encode()).hexdigest() if configured_secret else ""
    if not expected or not hmac.compare_digest(x_telegram_bot_api_secret_token or "", expected):
        raise HTTPException(403, "Invalid Telegram webhook secret")
    message = update.get("message") or {}
    text = str(message.get("text") or "").strip()
    chat_id = (message.get("chat") or {}).get("id")
    token = text.split(maxsplit=1)[1] if text.startswith("/start ") else ""
    business_id = business_from_token(token)
    if not business_id or chat_id is None:
        return {"ok": True, "connected": False}
    encrypted = SourceCredentialVault().encrypt({"access_token": str(chat_id)}, business_id=business_id, source_connection_id=business_id, provider="telegram")
    await repository.request("POST", "telegram_connections", params={"on_conflict": "business_id"}, json={"business_id": business_id, "encrypted_chat_id": encrypted, "enabled": True}, prefer="resolution=merge-duplicates")
    return {"ok": True, "connected": True}


@app.post("/api/mentions/ingest", response_model=ProcessedMention)
async def ingest(item: RawItem, business_id: UUID, context: AuthContext = Depends(require_user)) -> ProcessedMention:
    await require_business_member(context, business_id)
    return await process_item(business_id, item)


@app.get("/api/mentions", response_model=list[ProcessedMention])
async def list_mentions(business_id: UUID, context: AuthContext = Depends(require_user)) -> list[ProcessedMention]:
    await require_business_member(context, business_id)
    if repository.configured:
        try:
            return _visible_product_mentions(await repository.list_processed(business_id))
        except RepositoryUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
    return _visible_product_mentions([x for x in processed if x.mention.business_id == business_id])


@app.patch("/api/mentions/{mention_id}", response_model=ProcessedMention)
async def update_mention(mention_id: UUID, update: MentionUpdate, context: AuthContext = Depends(require_user)) -> ProcessedMention:
    item = await repository.get_processed(str(mention_id)) if repository.configured else next((row for row in processed if row.mention.id == mention_id), None)
    if not item:
        raise HTTPException(404, "Mention not found")
    await require_business_member(context, item.mention.business_id)
    values = {key: (value.value if hasattr(value, "value") else value) for key, value in update.model_dump(exclude_none=True).items()}
    if "reply_draft" in values and values["reply_draft"] != item.mention.reply_draft:
        values.setdefault("reply_status", ReplyStatus.draft.value)
    if repository.configured:
        await repository.request("PATCH", "mentions", params={"id": f"eq.{mention_id}", "business_id": f"eq.{item.mention.business_id}"}, json=values)
        updated = await repository.get_processed(str(mention_id))
        if not updated:
            raise HTTPException(404, "Mention not found")
        return updated
    item.mention = item.mention.model_copy(update=values)
    return item


@app.post("/api/mentions/{mention_id}/ignore-author", response_model=list[ProcessedMention])
async def ignore_author(mention_id: UUID, payload: dict = Body(...), context: AuthContext = Depends(require_user)) -> list[ProcessedMention]:
    item = await repository.get_processed(str(mention_id)) if repository.configured else next((row for row in processed if row.mention.id == mention_id), None)
    if not item:
        raise HTTPException(404, "Mention not found")
    await require_business_member(context, item.mention.business_id)
    author_key = str(item.mention.metadata.get("author_key") or "").strip()
    if not author_key:
        raise HTTPException(422, "This mention has no stable author identifier or author name")
    ignored = bool(payload.get("ignored", True))
    if repository.configured:
        await repository.set_author_ignored(item.mention.business_id, item.mention.source, author_key, ignored)
        return await repository.list_processed(item.mention.business_id)
    key = (item.mention.business_id, item.mention.source, author_key)
    ignored_authors.add(key) if ignored else ignored_authors.discard(key)
    for row in processed:
        if row.mention.business_id == key[0] and row.mention.source == key[1] and row.mention.metadata.get("author_key") == key[2]:
            row.mention = row.mention.model_copy(update={"include_in_analysis": not ignored})
            if ignored:
                row.risk = RiskResult(score=0, level="Excluded", reasons=["Ignored author"])
    return [row for row in processed if row.mention.business_id == item.mention.business_id]


@app.post("/api/mentions/{mention_id}/reply", response_model=ProcessedMention)
async def create_reply_draft(mention_id: UUID, request: ReplyDraftRequest, context: AuthContext = Depends(require_user)) -> ProcessedMention:
    item = await repository.get_processed(str(mention_id)) if repository.configured else next((row for row in processed if row.mention.id == mention_id), None)
    if not item:
        raise HTTPException(404, "Mention not found")
    await require_business_member(context, item.mention.business_id)
    if item.mention.reply_draft and not request.regenerate:
        return item
    draft = await generate_reply_draft(item.mention.text, item.analysis.sentiment, item.analysis.language, item.mention.content_type.value)
    now = datetime.now(timezone.utc)
    values = {"reply_draft": draft, "reply_generated_at": now.isoformat(), "reply_status": ReplyStatus.draft.value}
    if repository.configured:
        await repository.request("PATCH", "mentions", params={"id": f"eq.{mention_id}", "business_id": f"eq.{item.mention.business_id}"}, json=values)
        updated = await repository.get_processed(str(mention_id))
        if updated:
            return updated
    item.mention = item.mention.model_copy(update={"reply_draft": draft, "reply_generated_at": now, "reply_status": ReplyStatus.draft})
    return item


@app.post("/api/manual/import", response_model=list[ProcessedMention])
async def manual_import(request: ManualImportRequest, context: AuthContext = Depends(require_user)) -> list[ProcessedMention]:
    await require_business_member(context, request.business_id)
    rows: list[dict[str, str]] = []
    if request.csv_content:
        reader = csv.DictReader(io.StringIO(request.csv_content))
        if not reader.fieldnames or "text" not in {name.strip().lower() for name in reader.fieldnames}:
            raise HTTPException(422, "CSV must contain a text column")
        rows.extend({str(key).strip().lower(): str(value or "").strip() for key, value in row.items()} for row in reader)
    if request.text and request.text.strip():
        rows.append({"text": request.text.strip(), "source": "manual"})
    if not rows:
        raise HTTPException(422, "Paste feedback or upload a CSV file")
    results: list[ProcessedMention] = []
    for index, row in enumerate(rows[:500]):
        text = row.get("text", "").strip()
        if not text:
            continue
        rating = None
        try:
            rating = float(row["rating"]) if row.get("rating") else None
        except ValueError:
            pass
        published_at = None
        if row.get("published_at"):
            try:
                published_at = datetime.fromisoformat(row["published_at"].replace("Z", "+00:00"))
            except ValueError:
                pass
        results.append(await process_item(request.business_id, RawItem(source=row.get("source") or "manual", source_type=MentionType.review, external_id=f"manual-{hashlib.sha256(f'{index}|{text}'.encode()).hexdigest()}", external_url=row.get("url") or None, author_name=row.get("author") or None, text=text, rating=rating, published_at=published_at, metadata={"origin": "manual", "author_type": "customer"})))
    return results


def _period_bounds(days: int) -> tuple[date, date]:
    end = date.today()
    return end - timedelta(days=max(1, min(days, 365)) - 1), end


@app.get("/api/analytics")
async def analytics(business_id: UUID, days: int = 30, context: AuthContext = Depends(require_user)) -> dict:
    await require_business_member(context, business_id)
    mentions = _visible_product_mentions(await repository.list_processed(business_id) if repository.configured else [x for x in processed if x.mention.business_id == business_id])
    start, end = _period_bounds(days)
    rows = [item for item in mentions if item.mention.include_in_analysis and item.mention.collected_at.date() >= start]
    counts = Counter(item.analysis.sentiment for item in rows)
    aliases: list[str] = []
    if repository.configured:
        business = await repository.request("GET", "businesses", params={"select": "name,aliases", "id": f"eq.{business_id}", "limit": "1"})
        if business:
            aliases = [business[0].get("name") or "", *(business[0].get("aliases") or [])]
    topics = top_topics((item.mention.text for item in rows), aliases)
    return {"period_start": start.isoformat(), "period_end": end.isoformat(), "total": len(rows), "positive": counts["positive"], "negative": counts["negative"], "neutral": counts["neutral"] + counts["mixed"], "sentiment": {key: counts[key] for key in ("positive", "negative", "neutral", "mixed")}, "top_keywords": [{"word": word, "count": count} for word, count in topics]}


@app.get("/api/recommendations")
async def recommendations(business_id: UUID, days: int = 30, refresh: bool = False, context: AuthContext = Depends(require_user)) -> dict:
    await require_business_member(context, business_id)
    start, end = _period_bounds(days)
    mentions = _visible_product_mentions(await repository.list_processed(business_id) if repository.configured else [x for x in processed if x.mention.business_id == business_id])
    rows = [item for item in mentions if item.mention.include_in_analysis and item.mention.collected_at.date() >= start]
    industry = "this business"
    if repository.configured:
        business_rows = await repository.request("GET", "businesses", params={"select": "industry", "id": f"eq.{business_id}", "limit": "1"})
        if business_rows and business_rows[0].get("industry"):
            industry = str(business_rows[0]["industry"])
    if not rows:
        return {
            "business_id": str(business_id),
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "score": 0, "summary": "Not enough data yet",
            "recommendations": {"urgent_fix": [], "improve": [], "keep_doing": []},
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
    aspect_sentiment = Counter((aspect.aspect, aspect.sentiment) for item in rows for aspect in item.analysis.aspects)
    high_risk = Counter(aspect.aspect for item in rows if item.risk.score >= 60 for aspect in item.analysis.aspects if aspect.sentiment == "negative")
    urgent = [f"Address {aspect} — {count} high-risk negative mentions" for aspect, count in high_risk.most_common(3) if count >= 2]
    negative = [(aspect, count) for (aspect, sentiment), count in aspect_sentiment.most_common() if sentiment == "negative" and count >= 2 and aspect not in dict(high_risk)]
    positive = [(aspect, count) for (aspect, sentiment), count in aspect_sentiment.most_common() if sentiment == "positive" and count >= 2]
    payload = {"score": 0, "summary": f"Evidence-based themes for {industry} from included mentions." if urgent or negative or positive else "Not enough data yet", "recommendations": {
        "urgent_fix": urgent,
        "improve": [f"Improve {aspect} — {count} negative mentions" for aspect, count in negative[:3]],
        "keep_doing": [f"Keep supporting {aspect} — {count} positive mentions" for aspect, count in positive[:3]],
    }}
    result = {"business_id": str(business_id), "period_start": start.isoformat(), "period_end": end.isoformat(), "score": payload["score"], "summary": payload["summary"], "recommendations": payload["recommendations"], "generated_at": datetime.now(timezone.utc).isoformat()}
    if repository.configured:
        try:
            return await repository.save_recommendation(business_id, start.isoformat(), end.isoformat(), payload)
        except RepositoryUnavailable:
            return result
    return result


@app.post("/api/reviews/extract", response_model=list[ExtractedReview])
async def extract_review_content(request: ReviewExtractionRequest, context: AuthContext = Depends(require_user)) -> list[ExtractedReview]:
    await require_business_member(context, request.business_id)
    try:
        reviews = await extract_reviews(request.content, request.platform_hint, request.source_url)
    except ReviewExtractionUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    return reviews


@app.post("/api/reviews/import", response_model=list[ProcessedMention])
async def import_extracted_reviews(request: ReviewImportRequest, context: AuthContext = Depends(require_user)) -> list[ProcessedMention]:
    await require_business_member(context, request.business_id)
    social = {"Instagram", "Threads", "TikTok", "Telegram"}
    results: list[ProcessedMention] = []
    for review in request.reviews:
        platform = review.source_platform.value
        source_type = MentionType.review
        if platform in social:
            source_type = MentionType.social_comment
        elif platform == "YouTube":
            source_type = MentionType.video_comment
        elif platform == "News":
            source_type = MentionType.news_article
        elif platform == "Forum_Blog":
            source_type = MentionType.forum
        published_at = datetime.combine(review.publish_date, time.min, timezone.utc) if review.publish_date else None
        item = RawItem(
            source=platform,
            source_type=source_type,
            external_id=review_external_id(review),
            author_name=None if review.author_name == "Unknown" else review.author_name,
            text=review.review_text,
            rating=review.rating,
            published_at=published_at,
            metadata={
                "origin": "review_extraction_engine",
                "estimated_sentiment": review.estimated_sentiment,
                "extracted_language": review.language,
                "date_raw": review.date_raw,
                "likes_count": review.likes_count,
                "is_reply": review.meta_info.is_reply,
                "business_reply": review.meta_info.business_reply,
                "extra_details": review.meta_info.extra_details,
            },
        )
        results.append(await process_item(request.business_id, item))
    return results


@app.post("/api/sources")
async def create_source(source: SourceCreate, context: AuthContext = Depends(require_user)) -> dict:
    await require_business_member(context, source.business_id)
    if source.source.lower().strip() in {"2gis", "2gis maps"} and source.source_url:
        try:
            source = source.model_copy(update={"source_url": normalize_twogis_business_url(str(source.source_url))})
        except ConnectorUnavailable as exc:
            raise HTTPException(422, str(exc)) from exc
    if repository.configured:
        try:
            return await repository.create_source(source)
        except SourceAlreadyConnected as exc:
            raise HTTPException(409, str(exc)) from exc
    mode = source.collection_mode.value
    if source.connection_type.value == "imported":
        status = "ready"
    elif mode == "api" and source.connection_type.value == "official":
        status = "oauth_required"
    elif not source.source_url:
        status = "setup_required"
    else:
        status = "active"
    payload = source.model_dump(mode="json") | {"id": f"source-{len(sources)+1}", "status": status}
    sources.append(payload)
    return payload


def _oauth_provider(source_name: str) -> str:
    normalized = source_name.lower().strip()
    if normalized in {"google", "google business", "google_business"}:
        return "google_business"
    if normalized in {"instagram", "instagram comments"}:
        return "instagram"
    raise HTTPException(422, "Encrypted OAuth credentials are supported for Google Business and Instagram")


@app.put("/api/sources/{source_id}/credentials")
async def save_source_credentials(source_id: UUID, credential: SourceOAuthCredential, context: AuthContext = Depends(require_user)) -> dict:
    if not repository.configured:
        raise HTTPException(503, "Supabase is required for encrypted source credentials")
    source = await repository.get_source(str(source_id))
    if not source:
        raise HTTPException(404, "Source not found")
    business_id = UUID(source["business_id"])
    await require_business_member(context, business_id)
    provider = _oauth_provider(str(source["source"]))
    if provider == "google_business" and not (credential.account_id and credential.location_id):
        raise HTTPException(422, "Google Business requires account_id and location_id")
    if provider == "instagram" and not (credential.instagram_user_id or credential.media_id):
        raise HTTPException(422, "Instagram requires instagram_user_id or media_id")
    payload = {
        "access_token": credential.access_token.get_secret_value(),
        "refresh_token": credential.refresh_token.get_secret_value() if credential.refresh_token else None,
        "account_id": credential.account_id,
        "location_id": credential.location_id,
        "instagram_user_id": credential.instagram_user_id,
        "media_id": credential.media_id,
    }
    try:
        encrypted = SourceCredentialVault().encrypt(
            payload,
            business_id=business_id,
            source_connection_id=source_id,
            provider=provider,
        )
        row = await repository.upsert_source_credential(
            source_id=str(source_id), business_id=business_id, provider=provider,
            encrypted_token=encrypted, expires_at=credential.expires_at,
        )
    except CredentialEncryptionError as exc:
        raise HTTPException(503, str(exc)) from exc
    await repository.update_source(str(source_id), {"status": "active", "error_message": None})
    return {"source_id": str(source_id), "provider": provider, "configured": True, "expires_at": row.get("expires_at")}


@app.get("/api/sources/{source_id}/credentials")
async def source_credentials_status(source_id: UUID, context: AuthContext = Depends(require_user)) -> dict:
    if not repository.configured:
        raise HTTPException(503, "Supabase is required for encrypted source credentials")
    source = await repository.get_source(str(source_id))
    if not source:
        raise HTTPException(404, "Source not found")
    business_id = UUID(source["business_id"])
    await require_business_member(context, business_id)
    row = await repository.get_source_credential(source_id=str(source_id), business_id=business_id)
    return {"source_id": str(source_id), "provider": row.get("provider") if row else _oauth_provider(str(source["source"])), "configured": bool(row), "expires_at": row.get("expires_at") if row else None}


@app.delete("/api/sources/{source_id}/credentials")
async def disconnect_source_credentials(source_id: UUID, context: AuthContext = Depends(require_user)) -> dict:
    if not repository.configured:
        raise HTTPException(503, "Supabase is required for encrypted source credentials")
    source = await repository.get_source(str(source_id))
    if not source:
        raise HTTPException(404, "Source not found")
    business_id = UUID(source["business_id"])
    await require_business_member(context, business_id)
    await repository.delete_source_credential(source_id=str(source_id), business_id=business_id)
    await repository.update_source(str(source_id), {"status": "oauth_required", "error_message": None})
    return {"source_id": str(source_id), "configured": False}


@app.post("/api/sources/{source_id}/poll")
async def poll_source(source_id: str, backfill: bool = False, context: AuthContext = Depends(require_user)) -> JSONResponse:
    source = await repository.get_source(source_id) if repository.configured else next((s for s in sources if s["id"] == source_id), None)
    if not source:
        raise HTTPException(404, "Source not found")
    business_id = UUID(source["business_id"])
    await require_business_member(context, business_id)
    effective_backfill = backfill
    stored_before = 0
    try:
        credential_payload = None
        if repository.configured:
            credential_row = await repository.get_source_credential(source_id=source_id, business_id=business_id)
            if credential_row:
                expires_at = credential_row.get("expires_at")
                if expires_at and datetime.fromisoformat(expires_at.replace("Z", "+00:00")) <= datetime.now(timezone.utc):
                    raise ConnectorUnavailable("The source OAuth token has expired; reconnect this source")
                credential_payload = SourceCredentialVault().decrypt(
                    credential_row["encrypted_token"],
                    business_id=source["business_id"],
                    source_connection_id=source_id,
                    provider=credential_row["provider"],
                )
        effective_backfill, stored_before = await _should_run_history_sync(source, business_id, backfill)
        last_seen_item_id = None if effective_backfill else source.get("last_seen_item_id")
        if repository.configured and last_seen_item_id:
            complete = await repository.external_item_is_complete(business_id, str(source["source"]), last_seen_item_id)
            if not complete:
                last_seen_item_id = None
        collection = await collector_registry.collect(source, credential_payload, last_seen_item_id, backfill=effective_backfill)
    except (ConnectorUnavailable, CredentialEncryptionError) as exc:
        if repository.configured:
            await repository.update_source(source_id, {"status": "error", "error_message": str(exc), "last_checked_at": datetime.now(timezone.utc).isoformat()})
        return JSONResponse(status_code=409, content={"status": "failed", "source": str(source.get("source", "unknown")), "provider": "credentials", "collected": 0, "new": 0, "duplicates": 0, "warnings": [], "error_code": "auth_required", "message": str(exc), "detail": str(exc)})
    except Exception as exc:
        if repository.configured:
            message = f"Source collection failed: {type(exc).__name__}"
            await repository.update_source(source_id, {"status": "error", "error_message": message, "last_checked_at": datetime.now(timezone.utc).isoformat()})
        message = f"Source collection failed: {type(exc).__name__}"
        return JSONResponse(status_code=502, content={"status": "failed", "source": str(source.get("source", "unknown")), "provider": "registry", "collected": 0, "new": 0, "duplicates": 0, "warnings": [], "error_code": "collection_failed", "message": message, "detail": message})
    if not collection.success:
        if repository.configured:
            source_status = collection.error_code if collection.error_code in {"setup_required", "collector_unavailable"} else "error"
            await repository.update_source(source_id, {"status": source_status, "error_message": collection.error_message, "last_checked_at": datetime.now(timezone.utc).isoformat()})
        return JSONResponse(status_code=409, content={
            "status": "failed", "source": collection.source, "provider": collection.provider,
            "collected": 0, "new": 0, "duplicates": 0, "warnings": collection.warnings,
            "error_code": collection.error_code, "message": collection.error_message, "detail": collection.error_message,
        })
    items = collection.items
    if items:
        source["last_seen_item_id"] = items[0].external_id
    source["active_collection_method"] = collection.provider
    results = [await process_item(business_id, item) for item in items]
    duplicates = sum(1 for result in results if result.duplicate)
    new_count = len(results) - duplicates
    stored_after = stored_before + new_count
    if repository.configured:
        try:
            stored_after = await repository.count_mentions(business_id, str(source["source"]))
        except RepositoryUnavailable:
            stored_after = stored_before + new_count
    threshold = _history_threshold(str(source.get("source", "")))
    historical_complete = not effective_backfill or bool(collection.metadata.get("history_complete")) or (threshold > 0 and stored_after >= threshold)
    if effective_backfill:
        collection.metadata["historical_complete"] = historical_complete
        collection.metadata["stored_before_sync"] = stored_before
        collection.metadata["total_stored_after_sync"] = stored_after
    if repository.configured:
        success_status = "discovery_monitoring" if collection.provider == "discovery" else ("active" if items else "no_new_items")
        update_values = {"active_collection_method": source["active_collection_method"], "last_checked_at": datetime.now(timezone.utc).isoformat(), "status": success_status, "error_message": None}
        if source.get("last_seen_item_id"):
            update_values["last_seen_item_id"] = source.get("last_seen_item_id")
        if effective_backfill and historical_complete:
            update_values["last_seen_published_at"] = datetime.now(timezone.utc).isoformat()
        await repository.update_source(source_id, update_values)
    logger.info(
        "source=%s provider=%s mode=%s parsed=%s new=%s duplicates=%s total_stored=%s historical_complete=%s",
        collection.source,
        collection.provider,
        "backfill" if effective_backfill else "incremental",
        collection.collected_count,
        new_count,
        duplicates,
        stored_after,
        historical_complete,
    )
    payload = {
        "status": "success", "source": collection.source, "provider": collection.provider,
        "mode": "backfill" if effective_backfill else "incremental",
        "collected": collection.collected_count, "parsed": collection.collected_count, "new": new_count,
        "duplicates": duplicates, "warnings": collection.warnings,
        "collection_metadata": collection.metadata,
        "historical_complete": historical_complete,
        "total_stored_after_sync": stored_after,
        "items": [result.model_dump(mode="json") for result in results],
        "message": "No new reviews" if not results else f"{new_count} new item(s)",
    }
    return JSONResponse(content=payload)


@app.patch("/api/sources/{source_id}")
async def edit_source(source_id: UUID, update: SourceUpdate, context: AuthContext = Depends(require_user)) -> dict:
    source = await repository.get_source(str(source_id)) if repository.configured else next((item for item in sources if item.get("id") == str(source_id)), None)
    if not source:
        raise HTTPException(404, "Source not found")
    await require_business_member(context, UUID(source["business_id"]))
    source_url = str(update.source_url) if update.source_url else None
    if str(source.get("source", "")).lower().strip() in {"2gis", "2gis maps"} and source_url:
        try:
            source_url = normalize_twogis_business_url(source_url)
        except ConnectorUnavailable as exc:
            raise HTTPException(422, str(exc)) from exc
    values = {"source_url": source_url, "collection_mode": update.collection_mode.value, "last_seen_item_id": None, "error_message": None, "active_collection_method": None, "status": "active"}
    if repository.configured:
        await repository.update_source(str(source_id), values)
        updated = await repository.get_source(str(source_id))
        return updated or source
    source.update(values)
    return source


@app.delete("/api/sources/{source_id}")
async def delete_source(source_id: UUID, context: AuthContext = Depends(require_user)) -> dict:
    source = await repository.get_source(str(source_id)) if repository.configured else next((item for item in sources if item.get("id") == str(source_id)), None)
    if not source:
        raise HTTPException(404, "Source not found")
    await require_business_member(context, UUID(source["business_id"]))
    if repository.configured:
        await repository.request("DELETE", "source_connections", params={"id": f"eq.{source_id}"})
    else:
        sources.remove(source)
    return {"deleted": True, "id": str(source_id)}


@app.post("/api/discover")
async def discover(request: DiscoveryRequest, context: AuthContext = Depends(require_user)) -> dict:
    await require_business_member(context, request.business_id)
    queries = fan_out(request.brand_name, request.aliases, request.city)
    provider = DiscoveryService()
    try:
        results, provider_status = await asyncio.wait_for(provider.search_many(queries, country="KZ", date_range="30d"), timeout=12)
    except DiscoveryNotConfigured as exc:
        raise HTTPException(503, str(exc)) from exc
    except asyncio.TimeoutError as exc:
        raise HTTPException(504, "Internet search timed out. Please try again.") from exc
    brand_terms = [value.casefold().strip() for value in [request.brand_name, *request.aliases] if len(value.strip()) >= 2]
    unique = {canonical_url(item.url): item for item in results if any(term in f"{item.title} {item.snippet}".casefold() for term in brand_terms)}
    if repository.configured and unique:
        await repository.request("POST", "web_discoveries", params={"on_conflict": "business_id,url"}, json=[{"business_id": str(request.business_id), "url": x.url, "title": x.title, "snippet": x.snippet, "relevance": x.relevance, **({"discovered_at": x.published_at.isoformat()} if x.published_at else {})} for x in unique.values()], prefer="resolution=merge-duplicates")
    logger.info("provider=%s query_count=%d raw_count=%d filtered_count=%d saved_count=%d", ",".join(str(x.get("provider")) for x in provider_status), len(queries), len(results), len(unique), len(unique) if repository.configured else 0)
    return {"queries_generated": len(queries), "results": list(unique.values()), "providers": provider_status, "window": "30d"}


@app.get("/api/admin/overview")
async def admin_overview(context: AuthContext = Depends(require_admin_context)) -> dict:
    try:
        bundle = await repository.admin_bundle()
        await repository.audit(context.user_id, "admin.overview.view")
    except RepositoryUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    businesses, sources, usage = bundle["businesses"], bundle["sources"], bundle["usage"]
    return {
        **bundle,
        "summary": {
            "workspaces": len(businesses),
            "active_sources": sum(1 for source in sources if source.get("status") == "active"),
            "source_errors": sum(1 for source in sources if source.get("error_message")),
            "ai_requests": len(usage),
            "estimated_cost_usd": round(sum(float(row.get("estimated_cost_usd") or 0) for row in usage), 4),
        },
    }


@app.patch("/api/admin/feature-flags/{key}")
async def update_feature_flag(key: str, payload: dict = Body(...), context: AuthContext = Depends(require_admin_context)) -> dict:
    enabled = bool(payload.get("enabled"))
    await repository.request("PATCH", "feature_flags", params={"key": f"eq.{key}"}, json={"enabled": enabled, "updated_by": context.user_id})
    await repository.audit(context.user_id, "feature_flag.update", "feature_flag", key, {"enabled": enabled})
    return {"key": key, "enabled": enabled}


@app.get("/api/admin/workspaces/{business_id}")
async def inspect_workspace(business_id: UUID, context: AuthContext = Depends(require_admin_context)) -> dict:
    businesses = await repository.request("GET", "businesses", params={"select": "*", "id": f"eq.{business_id}", "limit": "1"})
    if not businesses:
        raise HTTPException(404, "Workspace not found")
    sources = await repository.request("GET", "source_connections", params={"select": "id,source,status,last_checked_at,error_message", "business_id": f"eq.{business_id}", "order": "created_at"})
    mentions = await repository.request("GET", "mentions", params={"select": "id,source,collected_at", "business_id": f"eq.{business_id}", "order": "collected_at.desc", "limit": "20"})
    alerts = await repository.request("GET", "alerts", params={"select": "id,severity,status,created_at", "business_id": f"eq.{business_id}", "order": "created_at.desc", "limit": "20"})
    await repository.audit(context.user_id, "workspace.support_view", "business", str(business_id), {"read_only": True})
    return {"business": businesses[0], "sources": sources, "mention_count_sample": len(mentions), "recent_mentions": mentions, "recent_alerts": alerts, "read_only": True}


@app.patch("/api/admin/system-settings/{key}")
async def update_system_setting(key: str, payload: dict = Body(...), context: AuthContext = Depends(require_admin_context)) -> dict:
    await repository.request("PATCH", "system_settings", params={"key": f"eq.{key}"}, json={"value": payload.get("value", {}), "updated_by": context.user_id})
    await repository.audit(context.user_id, "system_setting.update", "system_setting", key, {"value": payload.get("value", {})})
    return {"key": key, "value": payload.get("value", {})}


frontend = Path(__file__).resolve().parents[2] / "frontend"
if frontend.exists():
    app.mount("/assets", StaticFiles(directory=frontend / "assets"), name="assets")
    app.mount("/static", StaticFiles(directory=frontend), name="static")

    def _browser_safe_config() -> dict[str, str]:
        return {
            "SUPABASE_URL": os.getenv("SUPABASE_URL", ""),
            "SUPABASE_ANON_KEY": os.getenv("SUPABASE_ANON_KEY", ""),
            "AUTH_REDIRECT_URL": os.getenv("FRONTEND_URL") or os.getenv("APP_BASE_URL", ""),
            "API_URL": os.getenv("API_URL", ""),
        }

    def _frontend_index() -> HTMLResponse:
        html = (frontend / "index.html").read_text(encoding="utf-8")
        inline_config = f'<script id="sarap-config" type="application/json">{json.dumps(_browser_safe_config())}</script>'
        html = re.sub(r'<script src="config\.js\?v=\d+"></script>', inline_config, html, count=1)
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    @app.get("/")
    def index() -> HTMLResponse:
        return _frontend_index()

    @app.get("/config.js")
    def browser_config() -> Response:
        """Serve browser-safe config as JavaScript when extensions block /api requests."""
        return Response(
            f"window.SARAP_CONFIG = {json.dumps(_browser_safe_config())};\n",
            media_type="application/javascript",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/{filename:path}")
    def frontend_file(filename: str) -> Response:
        candidate = (frontend / filename).resolve()
        if candidate.is_file() and frontend.resolve() in candidate.parents:
            return FileResponse(candidate, headers={"Cache-Control": "no-cache, must-revalidate"})
        return _frontend_index()
