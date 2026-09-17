from __future__ import annotations

from dataclasses import dataclass
import os
from uuid import UUID

from fastapi import Depends, Header, HTTPException
import httpx


@dataclass(frozen=True)
class AuthContext:
    user_id: str
    access_token: str
    demo: bool = False


async def require_user(authorization: str | None = Header(default=None)) -> AuthContext:
    supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
    anon_key = os.getenv("SUPABASE_ANON_KEY", "")
    if not supabase_url or not anon_key:
        if os.getenv("APP_ENV", "development") == "development":
            return AuthContext(user_id="development-demo", access_token="", demo=True)
        raise HTTPException(503, "Account service is not configured")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Authentication required")
    token = authorization.split(" ", 1)[1].strip()
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{supabase_url}/auth/v1/user", headers={"apikey": anon_key, "Authorization": f"Bearer {token}"})
    except httpx.HTTPError as exc:
        raise HTTPException(503, "Could not verify the account session") from exc
    if response.status_code != 200:
        raise HTTPException(401, "The account session is invalid or expired")
    user_id = response.json().get("id")
    if not user_id:
        raise HTTPException(401, "The account session is invalid")
    return AuthContext(user_id=user_id, access_token=token)


async def require_business_member(context: AuthContext, business_id: UUID) -> None:
    if context.demo:
        return
    supabase_url = os.environ["SUPABASE_URL"].rstrip("/")
    anon_key = os.environ["SUPABASE_ANON_KEY"]
    params = {"select": "business_id", "business_id": f"eq.{business_id}", "user_id": f"eq.{context.user_id}", "limit": "1"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{supabase_url}/rest/v1/business_members", params=params, headers={"apikey": anon_key, "Authorization": f"Bearer {context.access_token}"})
    except httpx.HTTPError as exc:
        raise HTTPException(503, "Could not verify workspace access") from exc
    if response.status_code != 200 or not response.json():
        raise HTTPException(403, "You do not have access to this business workspace")


async def require_admin_context(context: AuthContext = Depends(require_user)) -> AuthContext:
    if context.demo:
        raise HTTPException(403, "Administrator access is required")
    supabase_url = os.environ["SUPABASE_URL"].rstrip("/")
    anon_key = os.environ["SUPABASE_ANON_KEY"]
    params = {"select": "role", "id": f"eq.{context.user_id}", "limit": "1"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{supabase_url}/rest/v1/profiles", params=params, headers={"apikey": anon_key, "Authorization": f"Bearer {context.access_token}"})
    except httpx.HTTPError as exc:
        raise HTTPException(503, "Could not verify administrator access") from exc
    rows = response.json() if response.status_code == 200 else []
    if not rows or rows[0].get("role") != "admin":
        raise HTTPException(403, "Administrator access is required")
    return context
