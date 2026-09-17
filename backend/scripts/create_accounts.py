"""Create one confirmed admin and one clean confirmed test account.

Requires SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in backend/.env. Passwords
are generated, printed once, and never written to the repository.
"""
from __future__ import annotations

import os
import secrets
import string
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def password() -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%"
    return "S!" + "".join(secrets.choice(alphabet) for _ in range(18))


def create_user(client: httpx.Client, base: str, key: str, email: str, name: str, role: str) -> tuple[str, str]:
    generated = password()
    response = client.post(
        f"{base}/auth/v1/admin/users",
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
        json={"email": email, "password": generated, "email_confirm": True, "user_metadata": {"full_name": name}},
    )
    if response.status_code >= 400:
        raise SystemExit(f"Could not create {email}: {response.text}")
    user_id = response.json()["id"]
    profile = client.patch(
        f"{base}/rest/v1/profiles",
        params={"id": f"eq.{user_id}"},
        headers={"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"role": role, "full_name": name, "email": email},
    )
    if profile.status_code >= 400:
        raise SystemExit(f"Account created, but role update failed for {email}: {profile.text}")
    return email, generated


def main() -> None:
    base = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    admin_email = os.getenv("SARAP_ADMIN_EMAIL", "").strip()
    test_email = os.getenv("SARAP_TEST_EMAIL", "").strip()
    missing = [name for name, value in (("SUPABASE_URL", base), ("SUPABASE_SERVICE_ROLE_KEY", key), ("SARAP_ADMIN_EMAIL", admin_email), ("SARAP_TEST_EMAIL", test_email)) if not value]
    if missing:
        raise SystemExit("Missing: " + ", ".join(missing))
    with httpx.Client(timeout=20) as client:
        admin = create_user(client, base, key, admin_email, "SARAP Admin", "admin")
        test = create_user(client, base, key, test_email, "SARAP Test", "user")
    print(f"ADMIN_EMAIL={admin[0]}\nADMIN_PASSWORD={admin[1]}")
    print(f"TEST_EMAIL={test[0]}\nTEST_PASSWORD={test[1]}")
    print("The test user has no workspace and will start at onboarding.")


if __name__ == "__main__":
    main()
