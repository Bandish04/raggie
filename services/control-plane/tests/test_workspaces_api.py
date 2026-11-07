# SPDX-License-Identifier: Apache-2.0

from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest_asyncio
from httpx import ASGITransport

from raggie_control_plane.api.deps import get_conn, get_current_user
from raggie_control_plane.db.repositories import OrganizationRepo, WorkspaceRepo
from raggie_control_plane.main import app
from raggie_control_plane.models import Role, User


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
        yield client, org
    app.dependency_overrides.clear()


async def test_super_admin_lists_org_workspaces(super_client, conn) -> None:
    client, org = super_client
    await WorkspaceRepo(conn).create(org.id, "Support", "EXTERNAL")
    await WorkspaceRepo(conn).create(org.id, "HR", "INTERNAL")

    r = await client.get("/api/v1/workspaces")
    assert r.status_code == 200
    names = {w["name"] for w in r.json()}
    assert {"Support", "HR"} <= names


async def test_workspaces_requires_auth(super_client) -> None:
    # Drop the auth override to exercise the real dependency.
    client, _org = super_client
    app.dependency_overrides.pop(get_current_user, None)
    r = await client.get("/api/v1/workspaces")
    assert r.status_code == 401
