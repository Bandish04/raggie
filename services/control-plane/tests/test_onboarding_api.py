# SPDX-License-Identifier: Apache-2.0

import hashlib

import httpx
import pytest_asyncio
from httpx import ASGITransport

from raggie_control_plane.api.deps import get_conn
from raggie_control_plane.auth.setup_token import ensure_setup_token
from raggie_control_plane.config import settings
from raggie_control_plane.db.repositories import UserRepo
from raggie_control_plane.main import app

BOOT = {"email": "admin@acme.example", "password": "pw-1234567890", "org_name": "Acme"}


@pytest_asyncio.fixture
async def client(conn):
    """Client bound to the rolled-back test connection. No auth override: the
    real get_current_user runs, exercising the JWT path end-to-end."""
    # The shared test database may hold committed rows from other suites; make
    # this (rolled-back) transaction look like a fresh, never-bootstrapped install.
    await conn.execute("UPDATE users SET role = 'STAFF' WHERE role = 'SUPER_ADMIN'")
    await conn.execute("UPDATE system_settings SET is_onboarded = FALSE, setup_token_hash = NULL")

    async def _conn_override():
        yield conn

    app.dependency_overrides[get_conn] = _conn_override
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def test_full_onboarding_external_flow(client) -> None:
    r = await client.get("/api/v1/onboarding/state")
    assert r.status_code == 200
    assert r.json() == {
        "onboarded": False,
        "has_super_admin": False,
        "setup_token_required": False,  # test env, no SETUP_TOKEN configured
    }

    r = await client.post(
        "/api/v1/onboarding/bootstrap",
        json={"email": "admin@acme.example", "password": "pw-1234567890", "org_name": "Acme"},
    )
    assert r.status_code == 201
    token = r.json()["access_token"]

    # Bootstrap is single-use.
    r2 = await client.post(
        "/api/v1/onboarding/bootstrap",
        json={"email": "x@y.com", "password": "pw-1234567890", "org_name": "X"},
    )
    assert r2.status_code == 409

    # Choose EXTERNAL -> embed snippet, and onboarding completes.
    r = await client.post(
        "/api/v1/onboarding/workspace",
        headers={"Authorization": f"Bearer {token}"},
        json={"type": "EXTERNAL", "name": "Support"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["embed_snippet"] and "/widgets/embed.js?id=" in body["embed_snippet"]
    assert body["invite_token"] is None

    r = await client.get("/api/v1/onboarding/state")
    assert r.json()["onboarded"] is True


async def test_internal_flow_returns_invite_copy_link(client) -> None:
    r = await client.post(
        "/api/v1/onboarding/bootstrap",
        json={"email": "a@acme.example", "password": "pw-1234567890", "org_name": "Acme"},
    )
    token = r.json()["access_token"]

    r = await client.post(
        "/api/v1/onboarding/workspace",
        headers={"Authorization": f"Bearer {token}"},
        json={"type": "INTERNAL", "name": "Team", "invite_email": "mate@acme.example"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["invite_token"]  # copy-link token returned once
    assert body["embed_snippet"] is None


async def test_workspace_setup_requires_auth(client) -> None:
    r = await client.post("/api/v1/onboarding/workspace", json={"type": "EXTERNAL", "name": "X"})
    assert r.status_code == 401


async def test_logout_revokes_session_server_side(client) -> None:
    r = await client.post(
        "/api/v1/onboarding/bootstrap",
        json={"email": "admin@acme.example", "password": "pw-1234567890", "org_name": "Acme"},
    )
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 200
    assert (await client.post("/api/v1/auth/logout", headers=headers)).status_code == 204
    assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 401


async def test_deactivated_user_is_rejected_immediately(client, conn) -> None:
    r = await client.post(
        "/api/v1/onboarding/bootstrap",
        json={"email": "admin@acme.example", "password": "pw-1234567890", "org_name": "Acme"},
    )
    token = r.json()["access_token"]
    user = await UserRepo(conn).get_by_email("admin@acme.example")
    assert user is not None
    await UserRepo(conn).set_active(user.id, False)

    r = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


# ── Setup token (bootstrap takeover protection) ──────────────────────────────
async def test_bootstrap_requires_configured_setup_token(client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "setup_token", "operator-chosen-setup-token-0123456789")
    r = await client.get("/api/v1/onboarding/state")
    assert r.json()["setup_token_required"] is True

    assert (await client.post("/api/v1/onboarding/bootstrap", json=BOOT)).status_code == 403
    r = await client.post("/api/v1/onboarding/bootstrap", json={**BOOT, "setup_token": "guess"})
    assert r.status_code == 403
    r = await client.post(
        "/api/v1/onboarding/bootstrap",
        json={**BOOT, "setup_token": "operator-chosen-setup-token-0123456789"},
    )
    assert r.status_code == 201


async def test_production_generates_hashed_one_time_token(client, conn, monkeypatch) -> None:
    monkeypatch.setattr(settings, "raggie_env", "production")
    monkeypatch.setattr(settings, "setup_token", "")
    await conn.execute("UPDATE system_settings SET setup_token_hash = NULL")

    plaintext = await ensure_setup_token(conn)
    assert plaintext and len(plaintext) >= 32
    stored = await conn.fetchval("SELECT setup_token_hash FROM system_settings")
    assert stored == hashlib.sha256(plaintext.encode()).hexdigest()
    assert plaintext not in stored
    # Generated once: another boot / replica does not rotate or re-log it.
    assert await ensure_setup_token(conn) is None
    assert await conn.fetchval("SELECT setup_token_hash FROM system_settings") == stored

    assert (await client.get("/api/v1/onboarding/state")).json()["setup_token_required"]
    assert (await client.post("/api/v1/onboarding/bootstrap", json=BOOT)).status_code == 403
    r = await client.post("/api/v1/onboarding/bootstrap", json={**BOOT, "setup_token": plaintext})
    assert r.status_code == 201
    # Consumed on success.
    assert await conn.fetchval("SELECT setup_token_hash FROM system_settings") is None
    assert await ensure_setup_token(conn) is None  # already bootstrapped


async def test_production_without_any_token_fails_closed(client, conn, monkeypatch) -> None:
    monkeypatch.setattr(settings, "raggie_env", "production")
    monkeypatch.setattr(settings, "setup_token", "")
    await conn.execute("UPDATE system_settings SET setup_token_hash = NULL")
    r = await client.post("/api/v1/onboarding/bootstrap", json={**BOOT, "setup_token": ""})
    assert r.status_code == 403
    assert not await UserRepo(conn).super_admin_exists()


async def test_bootstrap_user_is_platform_admin_and_serialized(client, conn) -> None:
    r = await client.post("/api/v1/onboarding/bootstrap", json=BOOT)
    assert r.status_code == 201
    user = await UserRepo(conn).get_by_email("admin@acme.example")
    assert user is not None and user.is_platform_admin is True
    # The existence check + insert ran under a transaction-scoped advisory lock.
    held = await conn.fetchval(
        "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory'"
        " AND pid = pg_backend_pid() AND granted"
    )
    assert held >= 1
