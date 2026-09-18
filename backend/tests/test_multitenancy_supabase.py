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
    from app.services.source_credentials import SourceCredentialVault

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
        test_email = os.getenv("SARAP_TEST_EMAIL", "").strip()
        if test_email:
            local, domain = test_email.rsplit("@", 1)
            email = f"{local}+sarap-{suffix}-{number}@{domain}"
            response = client.post(
                f"{base}/auth/v1/signup",
                headers={"apikey": anon, "Content-Type": "application/json"},
                json={"email": email, "password": password, "data": {"full_name": f"Isolation {number}", "business_name": f"Isolation Workspace {number}"}},
            )
            response.raise_for_status()
            user_id = response.json()["user"]["id"]
        else:
            email = f"sarap-isolation-{suffix}-{number}@example.test"
            response = client.post(
                f"{base}/auth/v1/admin/users",
                headers=auth_headers(service),
                json={"email": email, "password": password, "email_confirm": True, "user_metadata": {"full_name": f"Isolation {number}"}},
            )
            response.raise_for_status()
            user_id = response.json()["id"]
        users.append(user_id)
        confirmed = client.put(
            f"{base}/auth/v1/admin/users/{user_id}",
            headers=auth_headers(service),
            json={"email_confirm": True},
        )
        confirmed.raise_for_status()
        login = client.post(
            f"{base}/auth/v1/token",
            params={"grant_type": "password"},
            headers={"apikey": anon, "Content-Type": "application/json"},
            json={"email": email, "password": password},
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

            source_ids: dict[tuple[int, str], str] = {}
            original_ciphertexts: dict[str, str] = {}
            for business_id, token, number in ((business_a, token_a, 1), (business_b, token_b, 2)):
                source_specs = [
                    ("2GIS", "monitored", "auto", f"https://2gis.kz/almaty/firm/{1000 + number}/tab/reviews"),
                    ("Yandex Maps", "monitored", "auto", "https://127.0.0.1/reviews"),
                    ("Google Business", "official", "api", None),
                    ("Instagram", "official", "api", None),
                ]
                for source_name, connection_type, collection_mode, source_url in source_specs:
                    payload = {"business_id": business_id, "source": source_name, "connection_type": connection_type, "collection_mode": collection_mode}
                    if source_url:
                        payload["source_url"] = source_url
                    source = api.post("/api/sources", headers={"Authorization": f"Bearer {token}"}, json=payload)
                    assert source.status_code == 200, source.text
                    source_ids[(number, source_name)] = source.json()["id"]

                duplicate = api.post(
                    "/api/sources",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"business_id": business_id, "source": "Google Business", "connection_type": "official", "collection_mode": "api"},
                )
                assert duplicate.status_code == 409
                assert "already connected" in duplicate.json()["detail"].lower()

                google_id = source_ids[(number, "Google Business")]
                instagram_id = source_ids[(number, "Instagram")]
                for source_id, credential in (
                    (google_id, {"access_token": f"google-token-{suffix}-{number}-old", "refresh_token": f"google-refresh-{suffix}-{number}", "account_id": f"account-{number}", "location_id": f"location-{number}"}),
                    (instagram_id, {"access_token": f"instagram-token-{suffix}-{number}-old", "instagram_user_id": f"ig-user-{number}"}),
                ):
                    saved = api.put(f"/api/sources/{source_id}/credentials", headers={"Authorization": f"Bearer {token}"}, json=credential)
                    assert saved.status_code == 200, saved.text
                    status = api.get(f"/api/sources/{source_id}/credentials", headers={"Authorization": f"Bearer {token}"})
                    assert status.status_code == 200 and status.json()["configured"] is True

                before_disconnect = supabase.get(
                    f"{base}/rest/v1/source_credentials",
                    params={"select": "source_connection_id,encrypted_token", "business_id": f"eq.{business_id}"},
                    headers=auth_headers(service),
                )
                assert before_disconnect.status_code == 200, before_disconnect.text
                original_ciphertexts.update({row["source_connection_id"]: row["encrypted_token"] for row in before_disconnect.json()})

                for source_id, reconnect_payload in (
                    (google_id, {"access_token": f"google-token-{suffix}-{number}-new", "account_id": f"account-{number}", "location_id": f"location-{number}"}),
                    (instagram_id, {"access_token": f"instagram-token-{suffix}-{number}-new", "instagram_user_id": f"ig-user-{number}"}),
                ):
                    disconnected = api.delete(f"/api/sources/{source_id}/credentials", headers={"Authorization": f"Bearer {token}"})
                    assert disconnected.status_code == 200 and disconnected.json()["configured"] is False
                    status = api.get(f"/api/sources/{source_id}/credentials", headers={"Authorization": f"Bearer {token}"})
                    assert status.status_code == 200 and status.json()["configured"] is False
                    reconnected = api.put(f"/api/sources/{source_id}/credentials", headers={"Authorization": f"Bearer {token}"}, json=reconnect_payload)
                    assert reconnected.status_code == 200, reconnected.text

                for source_name in ("2GIS", "Yandex Maps", "Google Business", "Instagram"):
                    ingest = api.post(
                        "/api/mentions/ingest",
                        params={"business_id": business_id},
                        headers={"Authorization": f"Bearer {token}"},
                        json={"source": source_name, "source_type": "social_comment" if source_name == "Instagram" else "review", "external_id": f"{suffix}-{number}-{source_name}", "text": f"Private {source_name} client data {number}", "rating": None if source_name == "Instagram" else 5},
                    )
                    assert ingest.status_code == 200, ingest.text

            invalid_site = api.post(f"/api/sources/{source_ids[(1, 'Yandex Maps')]}/poll", headers={"Authorization": f"Bearer {token_a}"})
            assert invalid_site.status_code == 409
            assert "private network" in invalid_site.json()["detail"].lower()

            invalid_token = api.post(f"/api/sources/{source_ids[(1, 'Google Business')]}/poll", headers={"Authorization": f"Bearer {token_a}"})
            assert invalid_token.status_code == 409
            assert any(term in invalid_token.json()["detail"].lower() for term in ("invalid", "expired", "unavailable", "google business api returned"))

            own_a = api.get("/api/mentions", params={"business_id": business_a}, headers={"Authorization": f"Bearer {token_a}"})
            own_b = api.get("/api/mentions", params={"business_id": business_b}, headers={"Authorization": f"Bearer {token_b}"})
            assert own_a.status_code == own_b.status_code == 200
            assert {row["mention"]["source"] for row in own_a.json()} >= {"2GIS", "Yandex Maps", "Google Business", "Instagram"}
            assert all(row["mention"]["business_id"] == business_a for row in own_a.json())
            assert {row["mention"]["source"] for row in own_b.json()} >= {"2GIS", "Yandex Maps", "Google Business", "Instagram"}
            assert all(row["mention"]["business_id"] == business_b for row in own_b.json())

            assert api.get("/api/mentions", params={"business_id": business_b}, headers={"Authorization": f"Bearer {token_a}"}).status_code == 403
            assert api.get(f"/api/sources/{source_ids[(2, 'Google Business')]}/credentials", headers={"Authorization": f"Bearer {token_a}"}).status_code == 403

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
            oauth_ids = {source_ids[(number, source)] for number in (1, 2) for source in ("Google Business", "Instagram")}
            assert {row["source_connection_id"] for row in rows} == oauth_ids
            assert all("-token-" not in row["encrypted_token"] for row in rows)
            assert len({row["encrypted_token"] for row in rows}) == 4
            assert all(row["encrypted_token"] != original_ciphertexts[row["source_connection_id"]] for row in rows)

            expected = {
                (business_a, source_ids[(1, "Google Business")], "google_business"): f"google-token-{suffix}-1-new",
                (business_a, source_ids[(1, "Instagram")], "instagram"): f"instagram-token-{suffix}-1-new",
                (business_b, source_ids[(2, "Google Business")], "google_business"): f"google-token-{suffix}-2-new",
                (business_b, source_ids[(2, "Instagram")], "instagram"): f"instagram-token-{suffix}-2-new",
            }
            vault = SourceCredentialVault()
            for row in rows:
                provider = "instagram" if row["source_connection_id"] in {source_ids[(1, "Instagram")], source_ids[(2, "Instagram")]} else "google_business"
                payload = vault.decrypt(row["encrypted_token"], business_id=row["business_id"], source_connection_id=row["source_connection_id"], provider=provider)
                assert payload["access_token"] == expected[(row["business_id"], row["source_connection_id"], provider)]
        finally:
            for business_id in businesses:
                supabase.delete(f"{base}/rest/v1/businesses", params={"id": f"eq.{business_id}"}, headers=auth_headers(service))
            for user_id in users:
                supabase.delete(f"{base}/auth/v1/admin/users/{user_id}", headers=auth_headers(service))
