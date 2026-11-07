# SPDX-License-Identifier: Apache-2.0

"""Admin user management never lets an actor grant or act above their own rank:
a WORKSPACE_ADMIN (who does hold MANAGE_ORG in their org) can neither create nor
promote a SUPER_ADMIN, nor edit / deactivate / reset a SUPER_ADMIN; only a
platform admin may act on a platform admin."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from httpx import ASGITransport

from raggie_control_plane.api.deps import get_conn, get_current_user
from raggie_control_plane.db.repositories import OrganizationRepo, UserRepo
from raggie_control_plane.main import app
from raggie_control_plane.models import User


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


async def _org(conn):
    org = await OrganizationRepo(conn).create("Rank")
    users = UserRepo(conn)
    wa = await users.create("wa@rank.test", "h", "WORKSPACE_ADMIN", org_id=org.id)
    su = await users.create("su@rank.test", "h", "SUPER_ADMIN", org_id=org.id)
    staff = await users.create("st@rank.test", "h", "STAFF", org_id=org.id)
    return org, wa, su, staff


async def test_workspace_admin_cannot_create_a_super_admin(conn) -> None:
    org, wa, _su, _staff = await _org(conn)
    url = f"/api/v1/admin/orgs/{org.id}/users"
    async with _as(conn, wa) as c:
        denied = await c.post(url, json={"email": "boss@rank.test", "role": "SUPER_ADMIN"})
        allowed = await c.post(url, json={"email": "peer@rank.test", "role": "WORKSPACE_ADMIN"})
    assert (denied.status_code, allowed.status_code) == (403, 201)
    assert await UserRepo(conn).get_by_email("boss@rank.test") is None


async def test_workspace_admin_cannot_promote_to_super_admin(conn) -> None:
    org, wa, _su, staff = await _org(conn)
    async with _as(conn, wa) as c:
        r = await c.patch(
            f"/api/v1/admin/orgs/{org.id}/users/{staff.id}", json={"role": "SUPER_ADMIN"}
        )
    assert r.status_code == 403
    assert (await UserRepo(conn).get(staff.id)).role == "STAFF"


async def test_workspace_admin_cannot_act_on_a_super_admin(conn) -> None:
    org, wa, su, _staff = await _org(conn)
    base = f"/api/v1/admin/orgs/{org.id}/users/{su.id}"
    async with _as(conn, wa) as c:
        edit = await c.patch(base, json={"full_name": "Hijacked"})
        deactivate = await c.patch(f"{base}/active", json={"active": False})
        reset = await c.post(f"{base}/reset-password")
    assert (edit.status_code, deactivate.status_code, reset.status_code) == (403, 403, 403)
    target = await UserRepo(conn).get(su.id)
    assert target.is_active and target.full_name != "Hijacked"


async def test_only_a_platform_admin_resets_a_platform_admin(conn) -> None:
    org, _wa, su, _staff = await _org(conn)
    pa = await UserRepo(conn).create(
        "pa@rank.test", "h", "SUPER_ADMIN", org_id=org.id, is_platform_admin=True
    )
    async with _as(conn, su) as c:
        r = await c.post(f"/api/v1/admin/orgs/{org.id}/users/{pa.id}/reset-password")
    assert r.status_code == 403
