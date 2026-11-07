# SPDX-License-Identifier: Apache-2.0

"""Integrations: every scope (team / workspace / user) and sync target is
authorized, and another org's entity looks missing (404)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from httpx import ASGITransport

from raggie_control_plane.api.deps import get_conn, get_current_user
from raggie_control_plane.db.repositories import (
    IntegrationRepo,
    MembershipRepo,
    OrganizationRepo,
    TeamRepo,
    UserRepo,
    WorkspaceRepo,
)
from raggie_control_plane.main import app
from raggie_control_plane.models import User

API = "/api/v1/integrations"


@asynccontextmanager
async def _as(conn, user: User) -> AsyncIterator[httpx.AsyncClient]:
    async def _conn_override():
        yield conn

    app.dependency_overrides[get_conn] = _conn_override
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


async def _tenants(conn):
    """Org A (parent team -> child team -> workspace) and org B with a team-scoped
    Slack integration holding a secret channel."""
    orgs, users, teams = OrganizationRepo(conn), UserRepo(conn), TeamRepo(conn)
    org_a, org_b = await orgs.create("A"), await orgs.create("B")
    parent = await teams.create(org_a.id, "Parent")
    child = await teams.create(org_a.id, "Child", parent_team_id=parent.id)
    other = await teams.create(org_a.id, "Other")
    ws_a = await WorkspaceRepo(conn).create(org_a.id, "WS A", "INTERNAL", team_id=child.id)
    ws_other = await WorkspaceRepo(conn).create(org_a.id, "WS O", "INTERNAL", team_id=other.id)
    team_b = await teams.create(org_b.id, "Team B")
    ws_b = await WorkspaceRepo(conn).create(org_b.id, "WS B", "INTERNAL", team_id=team_b.id)
    integration_b = await IntegrationRepo(conn).upsert(
        org_id=org_b.id,
        scope_type="team",
        scope_id=team_b.id,
        provider="slack",
        target_workspace_id=None,
        display_name="B Slack",
        credentials_enc=None,
        config={"channel": "#b-secret"},
        status="connected",
        created_by=None,
    )
    wa = await users.create("wa@a.test", "h", "WORKSPACE_ADMIN", org_id=org_a.id)
    await MembershipRepo(conn).add_team_member(parent.id, wa.id, "WORKSPACE_ADMIN")
    su_a = await users.create("su@a.test", "h", "SUPER_ADMIN", org_id=org_a.id)
    staff = await users.create("st@a.test", "h", "STAFF", org_id=org_a.id)
    await MembershipRepo(conn).add_workspace_member(ws_a.id, staff.id, "STAFF")
    return {
        "org_a": org_a,
        "org_b": org_b,
        "parent": parent,
        "child": child,
        "other": other,
        "ws_a": ws_a,
        "ws_other": ws_other,
        "team_b": team_b,
        "ws_b": ws_b,
        "integration_b": integration_b,
        "wa": wa,
        "su_a": su_a,
        "staff": staff,
    }


def _team_connect(team_id, **extra) -> dict:
    return {
        "provider": "slack",
        "scope_type": "team",
        "scope_id": str(team_id),
        "display_name": "pwned",
        "config": {"channel": "#attacker"},
        **extra,
    }


async def test_workspace_admin_cannot_read_another_orgs_team_integrations(conn) -> None:
    t = await _tenants(conn)
    async with _as(conn, t["wa"]) as c:
        r = await c.get(API, params={"scope_type": "team", "scope_id": str(t["team_b"].id)})
    assert r.status_code == 404
    assert "#b-secret" not in r.text


async def test_workspace_admin_cannot_overwrite_another_orgs_team_integration(conn) -> None:
    t = await _tenants(conn)
    async with _as(conn, t["wa"]) as c:
        r = await c.post(API, json=_team_connect(t["team_b"].id))
    assert r.status_code == 404
    kept = await IntegrationRepo(conn).get(t["integration_b"].id)
    assert kept.display_name == "B Slack" and kept.config == {"channel": "#b-secret"}


async def test_workspace_admin_needs_membership_of_the_team(conn) -> None:
    t = await _tenants(conn)
    async with _as(conn, t["wa"]) as c:
        read = await c.get(API, params={"scope_type": "team", "scope_id": str(t["other"].id)})
        write = await c.post(API, json=_team_connect(t["other"].id))
    assert (read.status_code, write.status_code) == (403, 403)


async def test_team_membership_is_inherited_by_sub_teams(conn) -> None:
    t = await _tenants(conn)
    async with _as(conn, t["wa"]) as c:
        read = await c.get(API, params={"scope_type": "team", "scope_id": str(t["child"].id)})
        write = await c.post(API, json=_team_connect(t["child"].id))
    assert (read.status_code, write.status_code) == (200, 201)


async def test_super_admin_gets_404_for_another_orgs_scope(conn) -> None:
    t = await _tenants(conn)
    async with _as(conn, t["su_a"]) as c:
        team = await c.get(API, params={"scope_type": "team", "scope_id": str(t["team_b"].id)})
        ws = await c.get(API, params={"scope_type": "workspace", "scope_id": str(t["ws_b"].id)})
        target = await c.post(
            API, json=_team_connect(t["child"].id, target_workspace_id=str(t["ws_b"].id))
        )
    assert (team.status_code, ws.status_code, target.status_code) == (404, 404, 404)


async def test_user_scope_sync_target_needs_workspace_access(conn) -> None:
    t = await _tenants(conn)
    body = {"provider": "slack", "scope_type": "user", "scope_id": str(t["staff"].id)}
    async with _as(conn, t["staff"]) as c:
        foreign = await c.post(API, json={**body, "target_workspace_id": str(t["ws_other"].id)})
        own = await c.post(API, json={**body, "target_workspace_id": str(t["ws_a"].id)})
    assert (foreign.status_code, own.status_code) == (403, 201)
