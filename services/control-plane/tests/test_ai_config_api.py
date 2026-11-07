# SPDX-License-Identifier: Apache-2.0

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

import httpx
from httpx import ASGITransport

from raggie_control_plane.api.deps import get_conn, get_current_user
from raggie_control_plane.db.repositories import (
    MembershipRepo,
    OrganizationRepo,
    SettingsRepo,
    UserRepo,
    WorkspaceRepo,
)
from raggie_control_plane.main import app
from raggie_control_plane.models import Role, User


@asynccontextmanager
async def _client_for(conn, user: User) -> AsyncIterator[httpx.AsyncClient]:
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


def _super_admin() -> User:
    now = datetime.now(UTC)
    return User(
        id=uuid4(),
        org_id=None,
        email="su-models@raggie.test",
        role=Role.SUPER_ADMIN,
        is_platform_admin=True,
        created_at=now,
        updated_at=now,
    )


async def test_ai_config_default_must_remain_in_allowed_models(conn) -> None:
    await SettingsRepo(conn).update_ai_config(
        chat_default_model="local",
        chat_allowed_models=["local"],
        set_default=True,
        set_allowed=True,
    )

    async with _client_for(conn, _super_admin()) as client:
        response = await client.put(
            "/api/v1/admin/ai-config",
            json={"chat_allowed_models": ["managed"]},
        )
        assert response.status_code == 400

        response = await client.put(
            "/api/v1/admin/ai-config",
            json={
                "chat_default_model": "managed",
                "chat_allowed_models": ["managed"],
            },
        )
        assert response.status_code == 200
        assert response.json()["default_model"] == "managed"


async def test_ai_config_is_stored_as_json_array_and_object(conn) -> None:
    await SettingsRepo(conn).update_ai_config(
        chat_allowed_models=["local", "managed"],
        chat_model_aliases={"local": "Local", "managed": "Managed"},
        set_allowed=True,
        set_aliases=True,
    )

    row = await conn.fetchrow(
        "SELECT jsonb_typeof(chat_allowed_models) AS allowed_type,"
        " jsonb_typeof(chat_model_aliases) AS aliases_type,"
        " chat_allowed_models, chat_model_aliases"
        " FROM system_settings WHERE id = 'current'"
    )
    assert row["allowed_type"] == "array"
    assert row["aliases_type"] == "object"
    assert row["chat_allowed_models"] == ["local", "managed"]
    assert row["chat_model_aliases"] == {"local": "Local", "managed": "Managed"}


async def test_user_preferred_model_must_be_platform_allowed(conn) -> None:
    org = await OrganizationRepo(conn).create("Preference Org")
    user = await UserRepo(conn).create("prefs@raggie.test", "hash", "STAFF", org_id=org.id)
    await SettingsRepo(conn).update_ai_config(
        chat_allowed_models=["local"],
        set_allowed=True,
    )

    async with _client_for(conn, user) as client:
        response = await client.put(
            "/api/v1/auth/me/preferences",
            json={"preferred_chat_model": "managed"},
        )
        assert response.status_code == 400

        response = await client.put(
            "/api/v1/auth/me/preferences",
            json={"preferred_chat_model": " local "},
        )
        assert response.status_code == 200
        assert response.json()["preferred_chat_model"] == "local"


async def test_scheduled_task_model_must_be_platform_allowed(conn) -> None:
    org = await OrganizationRepo(conn).create("Scheduler Org")
    user = await UserRepo(conn).create("scheduler@raggie.test", "hash", "STAFF", org_id=org.id)
    workspace = await WorkspaceRepo(conn).create(org.id, "Ops", "INTERNAL")
    await MembershipRepo(conn).add_workspace_member(workspace.id, user.id, "STAFF")
    await SettingsRepo(conn).update_ai_config(
        chat_allowed_models=["local"],
        set_allowed=True,
    )
    body = {
        "name": "Daily report",
        "workspace_id": str(workspace.id),
        "prompt": "Summarize incidents",
        "cron": "0 9 * * *",
        "timezone": "Europe/Istanbul",
    }

    async with _client_for(conn, user) as client:
        response = await client.post(
            "/api/v1/scheduled-tasks",
            json={**body, "model": "managed"},
        )
        assert response.status_code == 400

        response = await client.post(
            "/api/v1/scheduled-tasks",
            json={**body, "model": " local "},
        )
        assert response.status_code == 201
        assert response.json()["model"] == "local"
