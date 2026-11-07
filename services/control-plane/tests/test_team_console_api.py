# SPDX-License-Identifier: Apache-2.0

"""Team-console endpoints: team detail/workspaces/documents, team & workspace
members, org users, and cross-org isolation."""

from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest_asyncio
from httpx import ASGITransport

from raggie_control_plane.api.deps import get_conn, get_current_user
from raggie_control_plane.db.repositories import (
    DocumentRepo,
    OrganizationRepo,
    TeamRepo,
    UserRepo,
    WorkspaceRepo,
)
from raggie_control_plane.main import app
from raggie_control_plane.models import Role, User

A = "/api/v1/admin"


@pytest_asyncio.fixture
async def admin_client(conn):
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
        yield client, conn
    app.dependency_overrides.clear()


async def test_team_detail_and_cross_org_404(admin_client) -> None:
    client, conn = admin_client
    org = await OrganizationRepo(conn).create("Acme")
    other = await OrganizationRepo(conn).create("Other")
    eng = await TeamRepo(conn).create(org.id, "Engineering")
    foreign = await TeamRepo(conn).create(other.id, "Foreign")

    r = await client.get(f"{A}/orgs/{org.id}/teams/{eng.id}")
    assert r.status_code == 200 and r.json()["name"] == "Engineering"

    assert (await client.get(f"{A}/orgs/{org.id}/teams/{uuid4()}")).status_code == 404
    # A team that exists but belongs to another org must 404 via this org's path.
    assert (await client.get(f"{A}/orgs/{org.id}/teams/{foreign.id}")).status_code == 404


async def test_team_workspaces_include_subteams(admin_client) -> None:
    client, conn = admin_client
    org = await OrganizationRepo(conn).create("Acme")
    eng = await TeamRepo(conn).create(org.id, "Engineering")
    backend = await TeamRepo(conn).create(org.id, "Backend", parent_team_id=eng.id)
    await WorkspaceRepo(conn).create(org.id, "W-eng", "INTERNAL", team_id=eng.id)
    await WorkspaceRepo(conn).create(org.id, "W-be", "INTERNAL", team_id=backend.id)

    r = await client.get(f"{A}/orgs/{org.id}/teams/{eng.id}/workspaces")
    assert {w["name"] for w in r.json()} == {"W-eng", "W-be"}  # parent pool includes sub-team
    r = await client.get(f"{A}/orgs/{org.id}/teams/{backend.id}/workspaces")
    assert {w["name"] for w in r.json()} == {"W-be"}


async def test_team_member_lifecycle(admin_client) -> None:
    client, conn = admin_client
    org = await OrganizationRepo(conn).create("Acme")
    team = await TeamRepo(conn).create(org.id, "Engineering")
    user = await UserRepo(conn).create("dev@acme.example", "h", "STAFF", org_id=org.id)
    base = f"{A}/orgs/{org.id}/teams/{team.id}/members"

    r = await client.post(base, json={"user_id": str(user.id), "role": "STAFF"})
    assert r.status_code == 204
    rows = (await client.get(base)).json()
    assert len(rows) == 1 and rows[0]["email"] == "dev@acme.example"
    assert (await client.delete(f"{base}/{user.id}")).status_code == 204
    assert (await client.get(base)).json() == []
    assert (await client.delete(f"{base}/{user.id}")).status_code == 404  # already gone


async def test_workspace_member_list_and_remove(admin_client) -> None:
    client, conn = admin_client
    org = await OrganizationRepo(conn).create("Acme")
    ws = await WorkspaceRepo(conn).create(org.id, "HR", "INTERNAL")
    user = await UserRepo(conn).create("hr@acme.example", "h", "STAFF", org_id=org.id)
    base = f"{A}/workspaces/{ws.id}/members"

    assert (await client.post(base, json={"user_id": str(user.id)})).status_code == 204
    assert any(m["email"] == "hr@acme.example" for m in (await client.get(base)).json())
    assert (await client.delete(f"{base}/{user.id}")).status_code == 204
    assert (await client.get(base)).json() == []


async def test_team_document_pool(admin_client) -> None:
    client, conn = admin_client
    org = await OrganizationRepo(conn).create("Acme")
    eng = await TeamRepo(conn).create(org.id, "Engineering")
    backend = await TeamRepo(conn).create(org.id, "Backend", parent_team_id=eng.id)
    other = await TeamRepo(conn).create(org.id, "Sales")
    w_be = await WorkspaceRepo(conn).create(org.id, "W-be", "INTERNAL", team_id=backend.id)
    w_sales = await WorkspaceRepo(conn).create(org.id, "W-sales", "INTERNAL", team_id=other.id)
    await DocumentRepo(conn).create(w_be.id, "spec.pdf", 10, "raggie_chunks_d1024")
    await DocumentRepo(conn).create(w_sales.id, "deck.pdf", 20, "raggie_chunks_d1024")

    # Engineering's pool includes its sub-team Backend's doc, not Sales'.
    eng_docs = (await client.get(f"{A}/orgs/{org.id}/teams/{eng.id}/documents")).json()
    assert {d["filename"] for d in eng_docs} == {"spec.pdf"}


async def test_list_org_users(admin_client) -> None:
    client, conn = admin_client
    org = await OrganizationRepo(conn).create("Acme")
    await UserRepo(conn).create("a@acme.example", "h", "STAFF", org_id=org.id)
    await UserRepo(conn).create("b@acme.example", "h", "WORKSPACE_ADMIN", org_id=org.id)

    emails = {u["email"] for u in (await client.get(f"{A}/orgs/{org.id}/users")).json()}
    assert {"a@acme.example", "b@acme.example"} <= emails
