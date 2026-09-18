from __future__ import annotations

import base64
import hashlib
import json
import os
from typing import Any
from uuid import UUID

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class CredentialEncryptionError(RuntimeError):
    """Raised when a source credential cannot be safely encrypted or decrypted."""


class SourceCredentialVault:
    """Encrypt OAuth payloads and bind them to one workspace and source."""

    version = "v1"

    def __init__(self, secret: str | None = None) -> None:
        configured = secret if secret is not None else os.getenv("SOURCE_TOKEN_ENCRYPTION_KEY", "")
        if len(configured.strip()) < 32:
            raise CredentialEncryptionError("SOURCE_TOKEN_ENCRYPTION_KEY must contain at least 32 characters")
        self._key = hashlib.sha256(configured.encode("utf-8")).digest()

    @staticmethod
    def _aad(business_id: UUID | str, source_connection_id: UUID | str, provider: str) -> bytes:
        return f"{business_id}:{source_connection_id}:{provider.lower().strip()}".encode("utf-8")

    def encrypt(self, payload: dict[str, Any], *, business_id: UUID | str, source_connection_id: UUID | str, provider: str) -> str:
        nonce = os.urandom(12)
        plaintext = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ciphertext = AESGCM(self._key).encrypt(nonce, plaintext, self._aad(business_id, source_connection_id, provider))
        return f"{self.version}:{base64.urlsafe_b64encode(nonce + ciphertext).decode('ascii')}"

    def decrypt(self, token: str, *, business_id: UUID | str, source_connection_id: UUID | str, provider: str) -> dict[str, Any]:
        try:
            version, encoded = token.split(":", 1)
            if version != self.version:
                raise ValueError("unsupported credential version")
            packed = base64.urlsafe_b64decode(encoded.encode("ascii"))
            plaintext = AESGCM(self._key).decrypt(packed[:12], packed[12:], self._aad(business_id, source_connection_id, provider))
            payload = json.loads(plaintext)
        except Exception as exc:
            raise CredentialEncryptionError("Source credential could not be decrypted") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("access_token"), str):
            raise CredentialEncryptionError("Source credential payload is invalid")
        return payload
