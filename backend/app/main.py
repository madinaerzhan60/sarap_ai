from __future__ import annotations

from pathlib import Path
import os
from uuid import UUID

from fastapi import Body, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from app.connectors.reviews import ConnectorUnavailable, connector_for
from app.connectors.search import FreeSearchProvider, fan_out
from app.models import DiscoveryRequest, ProcessedMention, RawItem, SourceCreate
from app.services.llm import analyze_with_cascade
from app.services.normalization import normalize
from app.services.risk import calculate
from app.services.telegram import send_alert
from app.security import AuthContext, require_admin_context, require_business_member, require_user
from app.repository import RepositoryUnavailable, repository

app = FastAPI(title="SARAP API", version="0.2.0", description="Reputation intelligence platform for Kazakhstan and the CIS")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_methods=["*"], allow_headers=["*"])

# Isolated fallback used only when the local demo runs without Supabase.
seen_hashes: set[str] = set()
processed: list[ProcessedMention] = []
sources: list[dict] = []


async def process_item(business_id: UUID, item: RawItem) -> ProcessedMention:
    mention = normalize(item, business_id)
    if repository.configured:
        previous = await repository.find_by_hash(business_id, mention.content_hash)
        if previous:
            return previous.model_copy(update={"duplicate": True})
    elif mention.content_hash in seen_hashes:
        previous = next(x for x in processed if x.mention.content_hash == mention.content_hash)
        return previous.model_copy(update={"duplicate": True})
    analysis = await analyze_with_cascade(mention.text)
    risk = calculate(mention, analysis)
    result = ProcessedMention(mention=mention, analysis=analysis, risk=risk, alert_created=risk.score >= 60)
    if repository.configured:
        result = await repository.persist_processed(result, "groq-gemini-cascade")
    else:
        seen_hashes.add(mention.content_hash)
        processed.append(result)
    if result.alert_created:
        try:
            send_alert(result)
        except OSError:
            pass
    return result


@app.get("/api/health")
def health() -> dict:
    accounts_ready = bool(os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_ANON_KEY"))
    return {"status": "ok", "service": "sarap-api", "accounts": "connected" if accounts_ready else "setup_required"}


@app.get("/api/public-config")
def public_config() -> dict:
    """Only browser-safe values. Never expose the service-role or provider keys."""
    return {
        "SUPABASE_URL": os.getenv("SUPABASE_URL", ""),
        "SUPABASE_ANON_KEY": os.getenv("SUPABASE_ANON_KEY", ""),
        "API_URL": os.getenv("APP_BASE_URL", ""),
    }


@app.post("/api/mentions/ingest", response_model=ProcessedMention)
async def ingest(item: RawItem, business_id: UUID, context: AuthContext = Depends(require_user)) -> ProcessedMention:
    await require_business_member(context, business_id)
    return await process_item(business_id, item)


@app.get("/api/mentions", response_model=list[ProcessedMention])
async def list_mentions(business_id: UUID, context: AuthContext = Depends(require_user)) -> list[ProcessedMention]:
    await require_business_member(context, business_id)
    if repository.configured:
        return await repository.list_processed(business_id)
    return [x for x in processed if x.mention.business_id == business_id]


@app.post("/api/sources")
async def create_source(source: SourceCreate, context: AuthContext = Depends(require_user)) -> dict:
    await require_business_member(context, source.business_id)
    if repository.configured:
        return await repository.create_source(source)
    mode = source.collection_mode.value
    status = "oauth_required" if mode == "api" and source.connection_type == "official" else "active"
    payload = source.model_dump(mode="json") | {"id": f"source-{len(sources)+1}", "status": status}
    sources.append(payload)
    return payload


@app.post("/api/sources/{source_id}/poll", response_model=list[ProcessedMention])
async def poll_source(source_id: str, context: AuthContext = Depends(require_user)) -> list[ProcessedMention]:
    source = await repository.get_source(source_id) if repository.configured else next((s for s in sources if s["id"] == source_id), None)
    if not source:
        raise HTTPException(404, "Source not found")
    await require_business_member(context, UUID(source["business_id"]))
    try:
        connector = connector_for(source)
        items = await connector.fetch_latest(source.get("last_seen_item_id"))
    except ConnectorUnavailable as exc:
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"Source collection failed: {type(exc).__name__}") from exc
    if items:
        source["last_seen_item_id"] = items[0].external_id
    source["active_collection_method"] = getattr(connector, "collection_method", connector.connection_type.value)
    if repository.configured:
        from datetime import datetime, timezone
        await repository.update_source(source_id, {"last_seen_item_id": source.get("last_seen_item_id"), "active_collection_method": source["active_collection_method"], "last_checked_at": datetime.now(timezone.utc).isoformat(), "status": "active", "error_message": None})
    return [await process_item(UUID(source["business_id"]), item) for item in items]


@app.post("/api/discover")
async def discover(request: DiscoveryRequest, context: AuthContext = Depends(require_user)) -> dict:
    await require_business_member(context, request.business_id)
    queries = fan_out(request.brand_name, request.aliases, request.city)
    provider = FreeSearchProvider()
    results = []
    for query in queries[:3]:
        results.extend(await provider.search(query, "all", "KZ", "7d"))
    unique = {item.url: item for item in results if item.relevance >= .7}
    if repository.configured and unique:
        await repository.request("POST", "web_discoveries", json=[{"business_id": str(request.business_id), "url": x.url, "title": x.title, "snippet": x.snippet, "relevance": x.relevance, **({"discovered_at": x.published_at.isoformat()} if x.published_at else {})} for x in unique.values()], prefer="resolution=merge-duplicates")
    return {"queries_generated": len(queries), "results": list(unique.values())}


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

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(frontend / "index.html")

    @app.get("/{filename:path}")
    def frontend_file(filename: str) -> FileResponse:
        candidate = (frontend / filename).resolve()
        if candidate.is_file() and frontend.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(frontend / "index.html")
