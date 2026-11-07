# SPDX-License-Identifier: Apache-2.0

"""Widget isolation regression — the widget audience must never reach the admin
surface, and the per-workspace CORS allow-list must reject wildcards."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import jwt
import pytest_asyncio
from httpx import ASGITransport

from raggie_control_plane.api.deps import get_conn, get_current_user
from raggie_control_plane.config import settings
from raggie_control_plane.db.repositories import OrganizationRepo, WorkspaceRepo
from raggie_control_plane.main import app
from raggie_control_plane.models import Role, User


def _mint(audience: str) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(uuid4()),
            "role": "SUPER_ADMIN",
            "org_id": None,
            "type": "access",
            "aud": audience,
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )


@pytest_asyncio.fixture
async def api(conn):
    async def _conn_override():
        yield conn

    app.dependency_overrides[get_conn] = _conn_override
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, conn
    app.dependency_overrides.clear()


async def test_widget_token_rejected_at_admin_surface(api) -> None:
    """A valid token minted for aud=widget must be forbidden on /api/v1/admin/*."""
    client, _conn = api
    token = _mint("widget")
    r = await client.get("/api/v1/admin/orgs", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


async def test_anonymous_rejected_at_admin_surface(api) -> None:
    client, _conn = api
    r = await client.get("/api/v1/admin/orgs")
    assert r.status_code == 401


async def test_admin_audience_passes_decode(api) -> None:
    """A correctly-scoped admin token clears the audience gate (it then fails the
    user lookup with 401, proving the 403 above is audience-specific, not blanket)."""
    client, _conn = api
    token = _mint("admin")
    r = await client.get("/api/v1/admin/orgs", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401  # unknown user, NOT 403 — audience was accepted


@pytest_asyncio.fixture
async def super_client(conn):
    org = await OrganizationRepo(conn).create("Acme")
    su = User(
        id=uuid4(),
        org_id=org.id,
        email="su@raggie.test",
        role=Role.SUPER_ADMIN,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    async def _conn_override():
        yield conn

    app.dependency_overrides[get_conn] = _conn_override
    app.dependency_overrides[get_current_user] = lambda: su
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, org, conn
    app.dependency_overrides.clear()


async def test_cors_wildcard_rejected(super_client) -> None:
    client, org, conn = super_client
    ws = await WorkspaceRepo(conn).create(org.id, "Support", "EXTERNAL")

    for bad in (["*"], ["https://*.acme.example"], ["https://acme.example/*"], ["not-an-origin"]):
        r = await client.put(
            f"/api/v1/admin/workspaces/{ws.id}/widget",
            json={"cors_allowed_origins": bad},
        )
        assert r.status_code == 422, f"expected reject for {bad}, got {r.status_code}"


async def test_cors_valid_origins_persist(super_client) -> None:
    client, org, conn = super_client
    ws = await WorkspaceRepo(conn).create(org.id, "Support", "EXTERNAL")

    r = await client.put(
        f"/api/v1/admin/workspaces/{ws.id}/widget",
        json={
            "widget_primary_color": "#9964ff",
            "cors_allowed_origins": ["https://acme.example", "http://localhost:3000/"],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["widget_primary_color"] == "#9964ff"
    # Trailing slash normalized away; both origins kept.
    assert body["cors_allowed_origins"] == ["https://acme.example", "http://localhost:3000"]

    saved = await WorkspaceRepo(conn).get(ws.id)
    assert saved is not None
    assert saved.cors_allowed_origins == ["https://acme.example", "http://localhost:3000"]
