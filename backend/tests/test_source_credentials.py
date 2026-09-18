import asyncio
from uuid import uuid4

import pytest

from app.connectors.reviews import ConnectorUnavailable, GoogleBusinessReviewsConnector, InstagramGraphCommentsConnector, connector_for
from app.models import SourceCreate
from app.repository import SourceAlreadyConnected, SupabaseRepository
from app.services.source_credentials import CredentialEncryptionError, SourceCredentialVault


def test_encrypted_credential_is_bound_to_business_and_source():
    business_a, business_b, source_id = uuid4(), uuid4(), uuid4()
    vault = SourceCredentialVault("a-test-key-that-is-at-least-thirty-two-characters")
    encrypted = vault.encrypt(
        {"access_token": "client-a-token", "account_id": "a", "location_id": "l"},
        business_id=business_a,
        source_connection_id=source_id,
        provider="google_business",
    )
    assert "client-a-token" not in encrypted
    assert vault.decrypt(encrypted, business_id=business_a, source_connection_id=source_id, provider="google_business")["access_token"] == "client-a-token"
    with pytest.raises(CredentialEncryptionError):
        vault.decrypt(encrypted, business_id=business_b, source_connection_id=source_id, provider="google_business")
    with pytest.raises(CredentialEncryptionError):
        vault.decrypt(encrypted, business_id=business_a, source_connection_id=uuid4(), provider="google_business")


def test_official_connectors_receive_explicit_per_source_credentials(monkeypatch):
    monkeypatch.setenv("GOOGLE_BUSINESS_ACCESS_TOKEN", "global-token-must-not-be-used")
    google = connector_for(
        {"source": "Google Business", "collection_mode": "api"},
        {"access_token": "workspace-token", "account_id": "account", "location_id": "location"},
    )
    instagram = connector_for(
        {"source": "Instagram", "collection_mode": "api"},
        {"access_token": "instagram-token", "instagram_user_id": "ig-user"},
    )
    assert isinstance(google, GoogleBusinessReviewsConnector)
    assert google.access_token == "workspace-token"
    assert isinstance(instagram, InstagramGraphCommentsConnector)
    assert instagram.access_token == "instagram-token"


def test_global_google_token_is_never_used(monkeypatch):
    monkeypatch.setenv("GOOGLE_BUSINESS_ACCESS_TOKEN", "legacy-global-token")
    with pytest.raises(ConnectorUnavailable, match="not connected for this workspace"):
        connector_for({"source": "Google Business", "collection_mode": "api"})


def test_private_source_url_returns_clear_error():
    with pytest.raises(ConnectorUnavailable, match="Private network"):
        connector_for({"source": "Yandex Maps", "collection_mode": "auto", "source_url": "https://127.0.0.1/reviews"})


def test_duplicate_source_returns_specific_error(monkeypatch):
    repository = SupabaseRepository()

    async def fake_request(method, path, **kwargs):
        return [{"id": "existing-source"}]

    monkeypatch.setattr(repository, "request", fake_request)
    source = SourceCreate(business_id=uuid4(), source="Google Business", connection_type="official", collection_mode="api")
    with pytest.raises(SourceAlreadyConnected, match="already connected"):
        asyncio.run(repository.create_source(source))


def test_repository_credential_lookup_always_filters_business_id(monkeypatch):
    repository = SupabaseRepository()
    captured = {}

    async def fake_request(method, path, **kwargs):
        captured.update({"method": method, "path": path, **kwargs})
        return []

    monkeypatch.setattr(repository, "request", fake_request)
    business_id = uuid4()
    assert asyncio.run(repository.get_source_credential(source_id=str(uuid4()), business_id=business_id)) is None
    assert captured["params"]["business_id"] == f"eq.{business_id}"
    assert captured["params"]["source_connection_id"].startswith("eq.")
