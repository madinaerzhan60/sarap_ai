"""Destructive-only-to-own-fixtures Supabase integration test.

Run against a migrated non-production project:
RUN_SUPABASE_INTEGRATION=1 PYTHONPATH=. pytest -q tests/test_multitenancy_supabase.py
"""

from __future__ import annotations

import os
import secrets
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient


pytestmark = pytest.mark.skipif(os.getenv("RUN_SUPABASE_INTEGRATION") != "1", reason="requires an explicitly selected migrated Supabase test project")


def test_two_new_clients_complete_flow_without_data_leakage():
    from app.main import app

    base = os.environ["SUPABASE_URL"].rstrip("/")
    anon = os.environ["SUPABASE_ANON_KEY"]
    service = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    suffix = secrets.token_hex(8)
    password = f"Sarap!{secrets.token_urlsafe(18)}"
    users: list[str] = []
    businesses: list[str] = []

    def auth_headers(key: str, token: str | None = None) -> dict[str, str]:
        return {"apikey": key, "Authorization": f"Bearer {token or key}", "Content-Type": "application/json"}

    def create_confirmed_user(client: httpx.Client, number: int) -> tuple[str, str]:
        response = client.post(
            f"{base}/auth/v1/admin/users",
            headers=auth_headers(service),
            json={"email": f"sarap-isolation-{suffix}-{number}@example.com", "password": password, "email_confirm": True, "user_metadata": {"full_name": f"Isolation {number}"}},
        )
        response.raise_for_status()
        user_id = response.json()["id"]
        users.append(user_id)
        login = client.post(
            f"{base}/auth/v1/token",
            params={"grant_type": "password"},
            headers={"apikey": anon, "Content-Type": "application/json"},
            json={"email": f"sarap-isolation-{suffix}-{number}@example.com", "password": password},
        )
        login.raise_for_status()
        return user_id, login.json()["access_token"]

    def complete_workspace(client: httpx.Client, token: str, number: int) -> str:
        response = client.post(
            f"{base}/rest/v1/rpc/complete_workspace",
            headers=auth_headers(anon, token),
            json={"p_name": f"Isolation Workspace {suffix} {number}", "p_city": "Almaty", "p_aliases": [f"isolation-{suffix}-{number}"]},
        )
        response.raise_for_status()
        business_id = response.json()
        businesses.append(business_id)
        return business_id

    with httpx.Client(timeout=20) as supabase, TestClient(app) as api:
        try:
            _, token_a = create_confirmed_user(supabase, 1)
            _, token_b = create_confirmed_user(supabase, 2)
            business_a = complete_workspace(supabase, token_a, 1)
            business_b = complete_workspace(supabase, token_b, 2)

            source_ids = []
            oauth_source_ids = []
            for business_id, token, number in ((business_a, token_a, 1), (business_b, token_b, 2)):
                source = api.post(
                    "/api/sources",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"business_id": business_id, "source": "CSV Import", "connection_type": "imported", "collection_mode": "auto"},
                )
                assert source.status_code == 200, source.text
                source_ids.append(source.json()["id"])
                oauth_source = api.post(
                    "/api/sources",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"business_id": business_id, "source": "Google Business", "connection_type": "official", "collection_mode": "api"},
                )
                assert oauth_source.status_code == 200, oauth_source.text
                oauth_source_id = oauth_source.json()["id"]
                oauth_source_ids.append(oauth_source_id)
                saved_credential = api.put(
                    f"/api/sources/{oauth_source_id}/credentials",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"access_token": f"private-oauth-token-{suffix}-{number}", "refresh_token": f"private-refresh-token-{suffix}-{number}", "account_id": f"account-{number}", "location_id": f"location-{number}"},
                )
                assert saved_credential.status_code == 200, saved_credential.text
                ingest = api.post(
                    "/api/mentions/ingest",
                    params={"business_id": business_id},
                    headers={"Authorization": f"Bearer {token}"},
                    json={"source": "CSV Import", "source_type": "review", "external_id": f"{suffix}-{number}", "text": f"Private client data {number}", "rating": 5},
                )
                assert ingest.status_code == 200, ingest.text

            own_a = api.get("/api/mentions", params={"business_id": business_a}, headers={"Authorization": f"Bearer {token_a}"})
            own_b = api.get("/api/mentions", params={"business_id": business_b}, headers={"Authorization": f"Bearer {token_b}"})
            assert own_a.status_code == own_b.status_code == 200
            assert any(row["mention"]["external_id"] == f"{suffix}-1" for row in own_a.json())
            assert all(row["mention"]["business_id"] == business_a for row in own_a.json())
            assert any(row["mention"]["external_id"] == f"{suffix}-2" for row in own_b.json())
            assert all(row["mention"]["business_id"] == business_b for row in own_b.json())

            assert api.get("/api/mentions", params={"business_id": business_b}, headers={"Authorization": f"Bearer {token_a}"}).status_code == 403
            assert api.get(f"/api/sources/{oauth_source_ids[1]}/credentials", headers={"Authorization": f"Bearer {token_a}"}).status_code == 403

            rls_a = supabase.get(f"{base}/rest/v1/source_connections", params={"select": "id,business_id"}, headers=auth_headers(anon, token_a))
            rls_b = supabase.get(f"{base}/rest/v1/source_connections", params={"select": "id,business_id"}, headers=auth_headers(anon, token_b))
            assert rls_a.status_code == rls_b.status_code == 200
            assert all(row["business_id"] == business_a for row in rls_a.json())
            assert all(row["business_id"] == business_b for row in rls_b.json())

            encrypted = supabase.get(
                f"{base}/rest/v1/source_credentials",
                params={"select": "business_id,source_connection_id,encrypted_token", "business_id": f"in.({business_a},{business_b})"},
                headers=auth_headers(service),
            )
            assert encrypted.status_code == 200, encrypted.text
            rows = encrypted.json()
            assert {row["business_id"] for row in rows} == {business_a, business_b}
            assert {row["source_connection_id"] for row in rows} == set(oauth_source_ids)
            assert all("private-oauth-token" not in row["encrypted_token"] for row in rows)
            assert len({row["encrypted_token"] for row in rows}) == 2
        finally:
            for business_id in businesses:
                supabase.delete(f"{base}/rest/v1/businesses", params={"id": f"eq.{business_id}"}, headers=auth_headers(service))
            for user_id in users:
                supabase.delete(f"{base}/auth/v1/admin/users/{user_id}", headers=auth_headers(service))
