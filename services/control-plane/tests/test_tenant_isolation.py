# SPDX-License-Identifier: Apache-2.0

"""Tenant isolation & privilege boundaries: org-scoped SUPER_ADMIN vs platform
admin, invite role escalation, cross-org team IDOR, the operator MCP credential,
and scheduled-task workspace membership."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
from httpx import ASGITransport

from raggie_control_plane.api.deps import get_conn, get_current_user, get_object_store
from raggie_control_plane.authz import Action, Authorizer
from raggie_control_plane.config import settings
from raggie_control_plane.db.repositories import (
    AuditRepo,
    MembershipRepo,
    OrganizationRepo,
    TeamRepo,
    UserRepo,
    WorkspaceRepo,
)
from raggie_control_plane.infra.objectstore import InMemoryObjectStore
from raggie_control_plane.main import app
from raggie_control_plane.models import User

A = "/api/v1/admin"


@asynccontextmanager
async def _as(conn, user: User) -> AsyncIterator[httpx.AsyncClient]:
    async def _conn_override():
        yield conn

    app.dependency_overrides[get_conn] = _conn_override
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_object_store] = InMemoryObjectStore
    try:
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


async def _two_orgs(conn):
    users = UserRepo(conn)
    org_a = await OrganizationRepo(conn).create("A Corp")
    org_b = await OrganizationRepo(conn).create("B Corp")
    team_b = await TeamRepo(conn).create(org_b.id, "B Team")
    ws_b = await WorkspaceRepo(conn).create(org_b.id, "B Docs", "INTERNAL", team_id=team_b.id)
    su_a = await users.create("su@a.test", "h", "SUPER_ADMIN", org_id=org_a.id)
    wa_a = await users.create("wa@a.test", "h", "WORKSPACE_ADMIN", org_id=org_a.id)
    return org_a, org_b, team_b, ws_b, su_a, wa_a


# ── 3. SUPER_ADMIN is org-scoped; platform admin is global ───────────────────
async def test_org_super_admin_authority_stops_at_org_boundary(conn) -> None:
    org_a, org_b, _team_b, ws_b, su_a, _wa = await _two_orgs(conn)
    ws_a = await WorkspaceRepo(conn).create(org_a.id, "A Docs", "INTERNAL")
    az = Authorizer(conn)
    assert await az.resolve(su_a, Action.MANAGE_ORG, org_id=org_a.id)
    assert await az.resolve(su_a, Action.MANAGE_WORKSPACE, workspace_id=ws_a.id)
    assert not await az.resolve(su_a, Action.MANAGE_ORG, org_id=org_b.id)
    assert not await az.resolve(su_a, Action.VIEW_WORKSPACE, workspace_id=ws_b.id)
    assert not await az.resolve(su_a, Action.MANAGE_SYSTEM)


async def test_platform_admin_is_global(conn) -> None:
    org_a, org_b, _team_b, ws_b, _su, _wa = await _two_orgs(conn)
    pa = await UserRepo(conn).create(
        "pa@a.test", "h", "SUPER_ADMIN", org_id=org_a.id, is_platform_admin=True
    )
    assert pa.is_platform_admin is True
    az = Authorizer(conn)
    assert await az.resolve(pa, Action.MANAGE_SYSTEM)
    assert await az.resolve(pa, Action.MANAGE_ORG, org_id=org_b.id)
    assert await az.resolve(pa, Action.MANAGE_WORKSPACE, workspace_id=ws_b.id)


async def test_org_super_admin_cannot_create_or_list_orgs(conn) -> None:
    *_rest, su_a, _wa = await _two_orgs(conn)
    async with _as(conn, su_a) as c:
        assert (await c.post(f"{A}/orgs", json={"name": "Evil"})).status_code == 403
        assert (await c.get(f"{A}/orgs")).status_code == 403


async def test_org_super_admin_cannot_touch_another_org(conn) -> None:
    _org_a, org_b, _team_b, ws_b, su_a, _wa = await _two_orgs(conn)
    async with _as(conn, su_a) as c:
        assert (await c.get(f"{A}/orgs/{org_b.id}/users")).status_code == 403
        r = await c.post(
            f"{A}/orgs/{org_b.id}/users", json={"email": "x@b.test", "role": "SUPER_ADMIN"}
        )
        assert r.status_code == 403
        assert (await c.get(f"{A}/workspaces/{ws_b.id}")).status_code == 403


async def test_org_super_admin_cannot_take_over_platform_admin(conn) -> None:
    org_a, *_rest, su_a, _wa = await _two_orgs(conn)
    pa = await UserRepo(conn).create(
        "pa@a.test", "h", "SUPER_ADMIN", org_id=org_a.id, is_platform_admin=True
    )
    async with _as(conn, su_a) as c:
        r = await c.post(f"{A}/orgs/{org_a.id}/users/{pa.id}/reset-password")
        assert r.status_code == 403
        r = await c.patch(f"{A}/orgs/{org_a.id}/users/{pa.id}/active", json={"active": False})
        assert r.status_code == 403
        r = await c.patch(f"{A}/orgs/{org_a.id}/users/{pa.id}", json={"role": "STAFF"})
        assert r.status_code == 403


async def test_platform_wide_settings_require_platform_admin(conn) -> None:
    *_rest, su_a, _wa = await _two_orgs(conn)
    async with _as(conn, su_a) as c:
        assert (await c.put(f"{A}/branding", json={"name": "Pwned"})).status_code == 403
        assert (await c.get(f"{A}/ai-config")).status_code == 403
        assert (await c.get(f"{A}/updates")).status_code == 403
        assert (await c.post(f"{A}/documents/retry-failed")).status_code == 403
        assert (await c.post(f"{A}/documents/reindex-all")).status_code == 403


async def test_orgless_super_admin_sees_no_workspaces(conn) -> None:
    _org_a, _org_b, _team_b, _ws_b, _su, _wa = await _two_orgs(conn)
    stray = await UserRepo(conn).create("stray@x.test", "h", "SUPER_ADMIN")
    async with _as(conn, stray) as c:
        r = await c.get("/api/v1/workspaces")
        assert r.status_code == 200 and r.json() == []


async def test_orgless_super_admin_cannot_read_every_orgs_audit_log(conn) -> None:
    # org_id NULL would otherwise mean "no org filter": the global audit log.
    org_a, org_b, *_rest = await _two_orgs(conn)
    audit = AuditRepo(conn)
    await audit.record("secret.a", org_id=org_a.id, target="a")
    await audit.record("secret.b", org_id=org_b.id, target="b")
    users = UserRepo(conn)
    stray = await users.create("stray@x.test", "h", "SUPER_ADMIN")
    root = await users.create("root@x.test", "h", "SUPER_ADMIN", is_platform_admin=True)
    async with _as(conn, stray) as c:
        denied = await c.get(f"{A}/audit")
    async with _as(conn, root) as c:
        everything = await c.get(f"{A}/audit")
    assert denied.status_code == 403 and "secret" not in denied.text
    assert everything.status_code == 200
    assert {"secret.a", "secret.b"} <= {e["action"] for e in everything.json()}


async def test_me_exposes_is_platform_admin(conn) -> None:
    *_rest, su_a, _wa = await _two_orgs(conn)
    async with _as(conn, su_a) as c:
        r = await c.get("/api/v1/auth/me")
        assert r.status_code == 200 and r.json()["is_platform_admin"] is False


# ── 1. Invite role escalation / foreign team & workspace ─────────────────────
async def test_workspace_admin_cannot_invite_higher_role(conn) -> None:
    *_rest, wa_a = await _two_orgs(conn)
    async with _as(conn, wa_a) as c:
        r = await c.post(
            "/api/v1/auth/invites", json={"email": "boss@a.test", "role": "SUPER_ADMIN"}
        )
        assert r.status_code == 403
        r = await c.post(
            "/api/v1/auth/invites", json={"email": "peer@a.test", "role": "WORKSPACE_ADMIN"}
        )
        assert r.status_code == 201


async def test_invite_rejects_foreign_team_and_workspace(conn) -> None:
    _org_a, _org_b, team_b, ws_b, su_a, _wa = await _two_orgs(conn)
    async with _as(conn, su_a) as c:
        r = await c.post(
            "/api/v1/auth/invites", json={"email": "t@a.test", "team_id": str(team_b.id)}
        )
        assert r.status_code == 400
        r = await c.post(
            "/api/v1/auth/invites", json={"email": "w@a.test", "workspace_id": str(ws_b.id)}
        )
        assert r.status_code == 400


async def test_invite_manager_must_belong_to_the_org(conn) -> None:
    # The accepted user's profile shows the manager's name, so a foreign manager
    # would leak another org's directory.
    org_a, org_b, _team_b, _ws_b, su_a, wa_a = await _two_orgs(conn)
    foreign = await UserRepo(conn).create("boss@b.test", "h", "STAFF", org_id=org_b.id)
    async with _as(conn, su_a) as c:
        bad = await c.post(
            "/api/v1/auth/invites",
            json={"email": "m1@a.test", "manager_user_id": str(foreign.id)},
        )
        missing = await c.post(
            "/api/v1/auth/invites", json={"email": "m2@a.test", "manager_user_id": str(uuid4())}
        )
        ok = await c.post(
            "/api/v1/auth/invites", json={"email": "m3@a.test", "manager_user_id": str(wa_a.id)}
        )
    assert (bad.status_code, missing.status_code, ok.status_code) == (400, 400, 201)


async def test_created_user_manager_must_belong_to_the_org(conn) -> None:
    org_a, org_b, _team_b, _ws_b, su_a, wa_a = await _two_orgs(conn)
    foreign = await UserRepo(conn).create("boss@b.test", "h", "STAFF", org_id=org_b.id)
    url = f"{A}/orgs/{org_a.id}/users"
    async with _as(conn, su_a) as c:
        bad = await c.post(url, json={"email": "c1@a.test", "manager_user_id": str(foreign.id)})
        missing = await c.post(url, json={"email": "c2@a.test", "manager_user_id": str(uuid4())})
        ok = await c.post(url, json={"email": "c3@a.test", "manager_user_id": str(wa_a.id)})
    assert (bad.status_code, missing.status_code, ok.status_code) == (400, 400, 201)
    assert bad.json()["detail"] == "manager not in organization"
    assert await UserRepo(conn).get_by_email("c1@a.test") is None
    assert ok.json()["user"]["manager_user_id"] == str(wa_a.id)


async def test_workspace_admin_cannot_resend_higher_role_invite(conn) -> None:
    *_rest, su_a, wa_a = await _two_orgs(conn)
    async with _as(conn, su_a) as c:
        r = await c.post(
            "/api/v1/auth/invites", json={"email": "boss@a.test", "role": "SUPER_ADMIN"}
        )
        assert r.status_code == 201
        invite_id = r.json()["invite_id"]
    async with _as(conn, wa_a) as c:
        r = await c.post(f"/api/v1/auth/invites/{invite_id}/resend")
        assert r.status_code == 403


# ── 2. Cross-org team IDOR ───────────────────────────────────────────────────
async def test_team_routes_reject_foreign_team(conn) -> None:
    org_a, _org_b, team_b, _ws_b, su_a, _wa = await _two_orgs(conn)
    victim = await UserRepo(conn).create("v@b.test", "h", "STAFF", org_id=team_b.org_id)
    await MembershipRepo(conn).add_team_member(team_b.id, victim.id, "STAFF")
    mine = await UserRepo(conn).create("m@a.test", "h", "STAFF", org_id=org_a.id)
    base = f"{A}/orgs/{org_a.id}/teams/{team_b.id}"
    async with _as(conn, su_a) as c:
        assert (await c.get(f"{base}/workspaces")).status_code == 404
        assert (await c.get(f"{base}/documents")).status_code == 404
        assert (await c.get(f"{base}/members")).status_code == 404
        r = await c.post(f"{base}/members", json={"user_id": str(mine.id)})
        assert r.status_code == 404
        assert (await c.delete(f"{base}/members/{victim.id}")).status_code == 404
        r = await c.post(
            f"{A}/orgs/{org_a.id}/teams", json={"name": "x", "parent_team_id": str(team_b.id)}
        )
        assert r.status_code == 404
        r = await c.post(
            f"{A}/orgs/{org_a.id}/workspaces",
            json={"name": "x", "type": "INTERNAL", "team_id": str(team_b.id)},
        )
        assert r.status_code == 404
    assert len(await MembershipRepo(conn).list_team_members(team_b.id)) == 1


async def test_cannot_add_foreign_user_as_member(conn) -> None:
    org_a, _org_b, team_b, _ws_b, su_a, _wa = await _two_orgs(conn)
    team_a = await TeamRepo(conn).create(org_a.id, "A Team")
    ws_a = await WorkspaceRepo(conn).create(org_a.id, "A Docs", "INTERNAL")
    foreign = await UserRepo(conn).create("f@b.test", "h", "STAFF", org_id=team_b.org_id)
    async with _as(conn, su_a) as c:
        r = await c.post(
            f"{A}/orgs/{org_a.id}/teams/{team_a.id}/members", json={"user_id": str(foreign.id)}
        )
        assert r.status_code == 404
        r = await c.post(f"{A}/workspaces/{ws_a.id}/members", json={"user_id": str(foreign.id)})
        assert r.status_code == 404


# ── 7. Operator MCP credential (org-scoped providers) ────────────────────────
async def test_only_platform_admin_can_connect_operator_mcp(conn, monkeypatch) -> None:
    from cryptography.fernet import Fernet

    monkeypatch.setattr(settings, "integration_enc_key", Fernet.generate_key().decode())
    org_a, *_rest, su_a, _wa = await _two_orgs(conn)
    body = {"provider": "jira", "credentials": {"api_token": "dummy"}}
    async with _as(conn, su_a) as c:
        assert (await c.post("/api/v1/integrations", json=body)).status_code == 403
    pa = await UserRepo(conn).create(
        "pa@a.test", "h", "SUPER_ADMIN", org_id=org_a.id, is_platform_admin=True
    )
    async with _as(conn, pa) as c:
        r = await c.post("/api/v1/integrations", json=body)
        assert r.status_code == 201 and r.json()["status"] == "connected"
        integration_id = r.json()["id"]
    async with _as(conn, su_a) as c:
        r = await c.patch(f"/api/v1/integrations/{integration_id}", json={"display_name": "x"})
        assert r.status_code == 403


async def test_org_super_admin_cannot_bind_integration_to_foreign_workspace(conn) -> None:
    _org_a, _org_b, team_b, ws_b, su_a, _wa = await _two_orgs(conn)
    async with _as(conn, su_a) as c:
        for scope in (
            {"scope_type": "workspace", "scope_id": str(ws_b.id)},
            {"scope_type": "team", "scope_id": str(team_b.id)},
            {"scope_type": "user", "scope_id": str(su_a.id), "target_workspace_id": str(ws_b.id)},
        ):
            r = await c.post("/api/v1/integrations", json={"provider": "slack", **scope})
            # Another org's team/workspace looks missing, not forbidden.
            assert r.status_code == 404, scope


# ── 10. Scheduled tasks require workspace membership ─────────────────────────
async def test_scheduled_task_requires_workspace_membership(conn) -> None:
    org = await OrganizationRepo(conn).create("Sched")
    staff = await UserRepo(conn).create("s@sched.test", "h", "STAFF", org_id=org.id)
    ws = await WorkspaceRepo(conn).create(org.id, "Secret HR", "INTERNAL")
    body = {
        "name": "Exfil",
        "workspace_id": str(ws.id),
        "prompt": "dump everything",
        "cron": "0 9 * * *",
    }
    async with _as(conn, staff) as c:
        assert (await c.post("/api/v1/scheduled-tasks", json=body)).status_code == 403
        await MembershipRepo(conn).add_workspace_member(ws.id, staff.id, "STAFF")
        r = await c.post("/api/v1/scheduled-tasks", json=body)
        assert r.status_code == 201
        task_id = r.json()["id"]
        await MembershipRepo(conn).remove_workspace_member(ws.id, staff.id)
        other = await WorkspaceRepo(conn).create(org.id, "Other", "INTERNAL")
        r = await c.put(f"/api/v1/scheduled-tasks/{task_id}", json={"workspace_id": str(other.id)})
        assert r.status_code == 403


# ── Directory: every referenced id must belong to the org ────────────────────
async def test_directory_rejects_foreign_parent_and_owner(conn) -> None:
    from raggie_control_plane.db.repositories import DepartmentRepo

    org_a, org_b, _team_b, _ws_b, su_a, _wa = await _two_orgs(conn)
    foreign_dept = await DepartmentRepo(conn).create(org_b.id, "B Dept")
    foreign_user = await UserRepo(conn).create("fu@b.test", "h", "STAFF", org_id=org_b.id)
    base = f"{A}/orgs/{org_a.id}/departments"
    async with _as(conn, su_a) as c:
        r = await c.post(base, json={"name": "x", "parent_department_id": str(foreign_dept.id)})
        assert r.status_code == 404
        r = await c.post(base, json={"name": "x", "owner_user_id": str(foreign_user.id)})
        assert r.status_code == 404
        mine = (await c.post(base, json={"name": "Mine"})).json()
        child = await c.post(base, json={"name": "Child", "parent_department_id": mine["id"]})
        assert child.status_code == 201
        r = await c.patch(
            f"{base}/{mine['id']}", json={"parent_department_id": str(foreign_dept.id)}
        )
        assert r.status_code == 404
        # A -> B -> A cycles are refused, not only self-parenting.
        r = await c.patch(f"{base}/{mine['id']}", json={"parent_department_id": child.json()["id"]})
        assert r.status_code == 400


# ── Platform admin grant / revoke ────────────────────────────────────────────
async def _only_platform_admin(conn, org_id):
    # Neutralize committed rows other suites may have left in the shared test DB.
    await conn.execute("UPDATE users SET is_platform_admin = FALSE WHERE is_platform_admin")
    return await UserRepo(conn).create(
        "root@a.test", "h", "SUPER_ADMIN", org_id=org_id, is_platform_admin=True
    )


async def test_platform_admin_grant_and_revoke(conn) -> None:
    org_a, org_b, *_rest, su_a, _wa = await _two_orgs(conn)
    root = await _only_platform_admin(conn, org_a.id)
    su_b = await UserRepo(conn).create("su@b.test", "h", "SUPER_ADMIN", org_id=org_b.id)
    url = f"{A}/users/{su_b.id}/platform-admin"
    async with _as(conn, su_a) as c:  # org SUPER_ADMIN: not allowed
        assert (await c.put(url, json={"is_platform_admin": True})).status_code == 403
    async with _as(conn, root) as c:
        r = await c.put(url, json={"is_platform_admin": True})
        assert r.status_code == 200 and r.json()["is_platform_admin"] is True
        r = await c.put(url, json={"is_platform_admin": False})
        assert r.status_code == 200 and r.json()["is_platform_admin"] is False
    actions = [
        r["action"]
        for r in await conn.fetch(
            "SELECT action FROM audit_log WHERE target = $1 ORDER BY created_at", str(su_b.id)
        )
    ]
    assert actions == ["user.platform_admin_granted", "user.platform_admin_revoked"]


async def test_cannot_revoke_last_platform_admin(conn) -> None:
    org_a, *_rest, su_a, _wa = await _two_orgs(conn)
    root = await _only_platform_admin(conn, org_a.id)
    async with _as(conn, root) as c:
        r = await c.put(f"{A}/users/{root.id}/platform-admin", json={"is_platform_admin": False})
        assert r.status_code == 409
        # With a second platform admin, self-revoke is allowed.
        await c.put(f"{A}/users/{su_a.id}/platform-admin", json={"is_platform_admin": True})
        r = await c.put(f"{A}/users/{root.id}/platform-admin", json={"is_platform_admin": False})
        assert r.status_code == 200


async def test_platform_admin_grant_requires_active_super_admin(conn) -> None:
    org_a, *_rest, wa_a = await _two_orgs(conn)
    root = await _only_platform_admin(conn, org_a.id)
    staff = await UserRepo(conn).create("st@a.test", "h", "STAFF", org_id=org_a.id)
    inactive = await UserRepo(conn).create("in@a.test", "h", "SUPER_ADMIN", org_id=org_a.id)
    await UserRepo(conn).set_active(inactive.id, False)
    async with _as(conn, root) as c:
        for u in (staff, wa_a, inactive):
            r = await c.put(f"{A}/users/{u.id}/platform-admin", json={"is_platform_admin": True})
            assert r.status_code == 409
        r = await c.put(
            f"{A}/users/00000000-0000-0000-0000-000000000000/platform-admin",
            json={"is_platform_admin": True},
        )
        assert r.status_code == 404


# ── Membership role labels obey the same rank rule as invites ────────────────
async def test_member_role_cannot_exceed_actor_rank(conn) -> None:
    org_a, *_rest, wa_a = await _two_orgs(conn)
    team = await TeamRepo(conn).create(org_a.id, "A Team")
    ws = await WorkspaceRepo(conn).create(org_a.id, "A WS", "INTERNAL", team_id=team.id)
    await MembershipRepo(conn).add_team_member(team.id, wa_a.id, "WORKSPACE_ADMIN")
    target = await UserRepo(conn).create("t@a.test", "h", "STAFF", org_id=org_a.id)
    async with _as(conn, wa_a) as c:
        for url in (
            f"{A}/workspaces/{ws.id}/members",
            f"{A}/orgs/{org_a.id}/teams/{team.id}/members",
        ):
            r = await c.post(url, json={"user_id": str(target.id), "role": "SUPER_ADMIN"})
            assert r.status_code == 403, url
            r = await c.post(url, json={"user_id": str(target.id), "role": "WORKSPACE_ADMIN"})
            assert r.status_code == 204, url


async def test_integration_belongs_to_the_org_of_its_scope(conn) -> None:
    org_a, *_rest, _wa = await _two_orgs(conn)
    ws_a = await WorkspaceRepo(conn).create(org_a.id, "A WS", "INTERNAL")
    org_p = await OrganizationRepo(conn).create("Platform Org")
    pa = await UserRepo(conn).create(
        "pa@p.test", "h", "SUPER_ADMIN", org_id=org_p.id, is_platform_admin=True
    )
    async with _as(conn, pa) as c:
        r = await c.post(
            "/api/v1/integrations",
            json={"provider": "slack", "scope_type": "workspace", "scope_id": str(ws_a.id)},
        )
        assert r.status_code == 201
        # Bound to org A (the workspace's org), not the acting platform admin's org.
        assert r.json()["org_id"] == str(org_a.id)


# ── Onboarding wizard mutates the GLOBAL onboarded flag: platform admin only ─
async def test_onboarding_workspace_requires_platform_admin(conn) -> None:
    org_a, *_rest, su_a, _wa = await _two_orgs(conn)
    await conn.execute(
        "INSERT INTO system_settings (id, is_onboarded) VALUES ('current', FALSE)"
        " ON CONFLICT (id) DO UPDATE SET is_onboarded = FALSE"
    )
    body = {"type": "INTERNAL", "name": "First"}
    async with _as(conn, su_a) as c:
        assert (await c.post("/api/v1/onboarding/workspace", json=body)).status_code == 403
    assert await conn.fetchval("SELECT is_onboarded FROM system_settings") is False
    pa = await UserRepo(conn).create(
        "boot@a.test", "h", "SUPER_ADMIN", org_id=org_a.id, is_platform_admin=True
    )
    async with _as(conn, pa) as c:
        assert (await c.post("/api/v1/onboarding/workspace", json=body)).status_code == 201
    assert await conn.fetchval("SELECT is_onboarded FROM system_settings") is True
