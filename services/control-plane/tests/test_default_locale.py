# SPDX-License-Identifier: Apache-2.0

"""Install default locale (DEFAULT_LOCALE -> NEXT_PUBLIC_DEFAULT_LOCALE -> en)
applied to every user-creation path; the schema default is now 'en'."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest
from httpx import ASGITransport

from raggie_control_plane.api.deps import get_conn, get_current_user
from raggie_control_plane.auth.oidc import OIDCClaims
from raggie_control_plane.auth.service import AuthService
from raggie_control_plane.config import (
    InsecureConfigurationError,
    Settings,
    settings,
    validate_runtime_secrets,
)
from raggie_control_plane.db.repositories import OrganizationRepo, UserRepo
from raggie_control_plane.main import app

PW = "locale-password-123"


@pytest.mark.parametrize(
    ("default", "next_public", "expected"),
    [
        ("", "", "en"),
        ("tr", "", "tr"),
        ("", "tr", "tr"),
        ("en", "tr", "en"),  # DEFAULT_LOCALE wins
        (" TR ", "", "tr"),
    ],
)
def test_install_locale_resolution(default, next_public, expected) -> None:
    cfg = Settings(_env_file=None, default_locale=default, next_public_default_locale=next_public)
    assert cfg.install_locale == expected


@pytest.mark.parametrize("env", ["development", "production"])
def test_unsupported_install_locale_fails_boot(env) -> None:
    cfg = Settings(_env_file=None, raggie_env=env, default_locale="de")
    with pytest.raises(InsecureConfigurationError, match="DEFAULT_LOCALE"):
        validate_runtime_secrets(cfg)


async def test_schema_default_is_english(conn) -> None:
    default = await conn.fetchval(
        "SELECT column_default FROM information_schema.columns"
        " WHERE table_name = 'users' AND column_name = 'locale'"
    )
    assert default is not None and "'en'" in default


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


@pytest.mark.parametrize("install", ["tr", "en"])
async def test_every_creation_path_uses_install_locale(conn, monkeypatch, install) -> None:
    monkeypatch.setattr(settings, "default_locale", install)
    users = UserRepo(conn)
    org = await OrganizationRepo(conn).create("Locale Org")

    # Bootstrap.
    await conn.execute("UPDATE users SET role = 'STAFF' WHERE role = 'SUPER_ADMIN'")
    async with _client(conn) as c:
        r = await c.post(
            "/api/v1/onboarding/bootstrap",
            json={"email": "boot@locale.test", "password": PW, "org_name": "B"},
        )
        assert r.status_code == 201
    # Invite accept (invite carries no locale).
    _inv, raw = await AuthService(conn).create_invite(org.id, "inv@locale.test", "STAFF")
    async with _client(conn) as c:
        r = await c.post("/api/v1/auth/invites/accept", json={"token": raw, "password": PW})
        assert r.status_code == 201
    # Admin create, without and with an explicit locale.
    admin = await users.create("adm@locale.test", "h", "SUPER_ADMIN", org_id=org.id)
    other = "en" if install == "tr" else "tr"
    async with _client(conn, admin) as c:
        url = f"/api/v1/admin/orgs/{org.id}/users"
        assert (await c.post(url, json={"email": "new@locale.test"})).status_code == 201
        r = await c.post(url, json={"email": "pinned@locale.test", "locale": other})
        assert r.status_code == 201
    # SSO and SCIM provisioning.
    sso = await AuthService(conn).resolve_sso_user(
        OIDCClaims("sub-l", "sso@locale.test", True, "https://idp"),
        org_id=org.id,
        default_role="STAFF",
    )
    scim = await users.create_external(
        "scim@locale.test", "STAFF", org_id=org.id, auth_provider="scim"
    )

    for email in ("boot@locale.test", "inv@locale.test", "new@locale.test"):
        assert (await users.get_by_email(email)).locale == install, email
    assert sso.locale == install and scim.locale == install
    assert (await users.get_by_email("pinned@locale.test")).locale == other
