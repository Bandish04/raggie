# SPDX-License-Identifier: Apache-2.0

"""One minimum password policy (>= 12 chars) on every password-setting path."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest
from httpx import ASGITransport

from raggie_control_plane.api.deps import get_conn, get_current_user
from raggie_control_plane.auth.service import AuthService
from raggie_control_plane.db.repositories import OrganizationRepo
from raggie_control_plane.main import app
from raggie_control_plane.security import MIN_PASSWORD_LENGTH, check_password_policy

SHORT = "Elev3n-char"  # 11 characters
GOOD = "twelve-chars-ok"


def test_validator_rules() -> None:
    assert MIN_PASSWORD_LENGTH == 12
    assert check_password_policy(GOOD) == GOOD
    for bad in (SHORT, " " * 20, "x" * 1025):
        with pytest.raises(ValueError):
            check_password_policy(bad)


@asynccontextmanager
async def _client(conn, user=None) -> AsyncIterator[httpx.AsyncClient]:
    async def _conn_override():
        yield conn

    app.dependency_overrides[get_conn] = _conn_override
    if user is not None:
        app.dependency_overrides[get_current_user] = lambda: user
    try:
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


async def test_bootstrap_enforces_policy(conn) -> None:
    await conn.execute("UPDATE users SET role = 'STAFF' WHERE role = 'SUPER_ADMIN'")
    async with _client(conn) as c:
        body = {"email": "a@pw.test", "org_name": "PW"}
        r = await c.post("/api/v1/onboarding/bootstrap", json={**body, "password": SHORT})
        assert r.status_code == 422
        r = await c.post("/api/v1/onboarding/bootstrap", json={**body, "password": GOOD})
        assert r.status_code == 201


async def test_invite_accept_enforces_policy(conn) -> None:
    org = await OrganizationRepo(conn).create("PW")
    _invite, raw = await AuthService(conn).create_invite(org.id, "new@pw.test", "STAFF")
    async with _client(conn) as c:
        r = await c.post("/api/v1/auth/invites/accept", json={"token": raw, "password": SHORT})
        assert r.status_code == 422
        r = await c.post("/api/v1/auth/invites/accept", json={"token": raw, "password": GOOD})
        assert r.status_code == 201


async def test_change_password_enforces_policy(conn) -> None:
    user = await AuthService(conn).register("me@pw.test", GOOD, "STAFF")
    async with _client(conn, user) as c:
        r = await c.post(
            "/api/v1/auth/change-password",
            json={"current_password": GOOD, "new_password": SHORT},
        )
        assert r.status_code == 422
        r = await c.post(
            "/api/v1/auth/change-password",
            json={"current_password": GOOD, "new_password": "another-good-one"},
        )
        assert r.status_code == 204


async def test_admin_create_user_enforces_policy(conn) -> None:
    org = await OrganizationRepo(conn).create("PW")
    admin = await AuthService(conn).register("adm@pw.test", GOOD, "SUPER_ADMIN", org_id=org.id)
    url = f"/api/v1/admin/orgs/{org.id}/users"
    async with _client(conn, admin) as c:
        r = await c.post(url, json={"email": "u1@pw.test", "password": SHORT})
        assert r.status_code == 422
        r = await c.post(url, json={"email": "u2@pw.test", "password": GOOD})
        assert r.status_code == 201
        r = await c.post(url, json={"email": "u3@pw.test"})  # generated temp password
        assert r.status_code == 201
        assert len(r.json()["temp_password"]) >= 12
