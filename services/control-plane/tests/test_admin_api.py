# SPDX-License-Identifier: Apache-2.0

from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest_asyncio
from httpx import ASGITransport

from raggie_control_plane.api.deps import get_conn, get_current_user
from raggie_control_plane.db.repositories import (
    OrganizationRepo,
    UserRepo,
    WorkspaceRepo,
)
from raggie_control_plane.main import app
from raggie_control_plane.models import Role, User


@pytest_asyncio.fixture
async def admin_client(conn):
    """An httpx client whose requests run against the rolled-back test connection,
    authenticated as a platform super admin (so guards pass)."""
    su = User(
        id=uuid4(),
        org_id=None,
        email="su@raggie.test",
        role=Role.SUPER_ADMIN,
        is_platform_admin=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    async def _conn_override():
        yield conn

    app.dependency_overrides[get_conn] = _conn_override
    app.dependency_overrides[get_current_user] = lambda: su
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


async def test_org_team_workspace_crud(admin_client) -> None:
    r = await admin_client.post("/api/v1/admin/orgs", json={"name": "Acme"})
    assert r.status_code == 201
    org_id = r.json()["id"]

    r = await admin_client.post(f"/api/v1/admin/orgs/{org_id}/teams", json={"name": "Engineering"})
    assert r.status_code == 201
    eng_id = r.json()["id"]

    # Nested sub-team.
    r = await admin_client.post(
        f"/api/v1/admin/orgs/{org_id}/teams",
        json={"name": "Backend", "parent_team_id": eng_id},
    )
    assert r.status_code == 201

    r = await admin_client.post(
        f"/api/v1/admin/orgs/{org_id}/workspaces",
        json={"name": "Docs", "type": "INTERNAL", "team_id": eng_id},
    )
    assert r.status_code == 201
    ws = r.json()
    assert ws["cors_allowed_origins"] == []
    ws_id = ws["id"]

    r = await admin_client.get(f"/api/v1/admin/orgs/{org_id}/workspaces")
    assert r.status_code == 200 and len(r.json()) == 1

    r = await admin_client.get(f"/api/v1/admin/workspaces/{ws_id}")
    assert r.status_code == 200 and r.json()["name"] == "Docs"


async def test_add_workspace_member(admin_client, conn) -> None:
    org = await OrganizationRepo(conn).create("Acme")
    ws = await WorkspaceRepo(conn).create(org.id, "HR", "INTERNAL")
    user = await UserRepo(conn).create("m@acme.example", "h", "STAFF", org_id=org.id)

    r = await admin_client.post(
        f"/api/v1/admin/workspaces/{ws.id}/members",
        json={"user_id": str(user.id), "role": "STAFF"},
    )
    assert r.status_code == 204


async def test_get_missing_workspace_returns_404(admin_client) -> None:
    r = await admin_client.get(f"/api/v1/admin/workspaces/{uuid4()}")
    assert r.status_code == 404


async def test_org_create_ignores_the_retired_embedding_dim(admin_client) -> None:
    """The embeddings gateway owns the dimension; older clients that still send
    embedding_dim are accepted and the field is dropped."""
    r = await admin_client.post("/api/v1/admin/orgs", json={"name": "Dim", "embedding_dim": 384})
    assert r.status_code == 201
    assert "embedding_dim" not in r.json()
