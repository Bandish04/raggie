# SPDX-License-Identifier: Apache-2.0

"""Durable user memory is double-gated: the MEMORY_ENABLED kill switch and the
per-workspace ``memory_enabled`` flag (default off)."""

from __future__ import annotations

from uuid import uuid4

import httpx
import pytest_asyncio
from httpx import ASGITransport

from raggie_control_plane.api.deps import get_conn, get_current_user
from raggie_control_plane.config import Settings, settings
from raggie_control_plane.db.repositories import (
    OrganizationRepo,
    UserMemoryRepo,
    UserRepo,
    WorkspaceRepo,
)
from raggie_control_plane.main import app


@pytest_asyncio.fixture
async def ctx(conn):
    org = await OrganizationRepo(conn).create("Mem")
    ws = await WorkspaceRepo(conn).create(org.id, "Mem", "INTERNAL")
    admin = await UserRepo(conn).create(
        f"sa-{uuid4().hex[:8]}@mem.test", "h", "SUPER_ADMIN", org_id=org.id
    )

    async def _conn_override():
        yield conn

    app.dependency_overrides[get_conn] = _conn_override
    app.dependency_overrides[get_current_user] = lambda: admin
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c, conn, ws, admin
    app.dependency_overrides.clear()


def test_memory_kill_switch_defaults_on() -> None:
    assert Settings(_env_file=None).memory_enabled is True


async def test_new_workspaces_have_memory_off(ctx) -> None:
    c, _conn, ws, _admin = ctx
    assert ws.memory_enabled is False
    body = (await c.get(f"/api/v1/admin/workspaces/{ws.id}/settings")).json()
    assert body["memory_enabled"] is False
    assert body["memory_available"] is True


async def test_memory_flag_toggles_independently(ctx) -> None:
    c, _conn, ws, _admin = ctx
    url = f"/api/v1/admin/workspaces/{ws.id}/settings"
    await c.put(url, json={"web_search_enabled": True})

    r = await c.put(url, json={"memory_enabled": True})

    assert r.status_code == 200
    assert r.json()["memory_enabled"] is True
    assert r.json()["web_search_enabled"] is True  # untouched by a partial update
    assert (await c.get(url)).json()["memory_enabled"] is True
    assert (await c.put(url, json={"memory_enabled": False})).json()["memory_enabled"] is False


async def test_settings_report_the_kill_switch(ctx, monkeypatch) -> None:
    c, _conn, ws, _admin = ctx
    monkeypatch.setattr(settings, "memory_enabled", False)
    body = (await c.get(f"/api/v1/admin/workspaces/{ws.id}/settings")).json()
    assert body["memory_available"] is False


async def test_workspace_create_accepts_memory_flag(ctx) -> None:
    c, _conn, ws, _admin = ctx
    r = await c.post(
        f"/api/v1/admin/orgs/{ws.org_id}/workspaces",
        json={"name": "With memory", "type": "INTERNAL", "memory_enabled": True},
    )
    assert r.status_code == 201 and r.json()["memory_enabled"] is True


async def test_import_is_refused_when_memory_is_globally_off(ctx, monkeypatch) -> None:
    c, conn, _ws, admin = ctx
    monkeypatch.setattr(settings, "memory_enabled", False)

    r = await c.post("/api/v1/auth/memory/import", json={"text": "- Likes tea"})

    assert r.status_code == 404 and "not enabled" in r.json()["detail"]
    assert await UserMemoryRepo(conn).list(admin.id) == []


async def test_stored_memory_stays_viewable_and_erasable_when_off(ctx, monkeypatch) -> None:
    """Turning memory off must never lock users out of what was already stored
    about them (KVKK/GDPR access + erasure)."""
    c, conn, _ws, admin = ctx
    await UserMemoryRepo(conn).add(admin.id, ["Likes tea"])
    monkeypatch.setattr(settings, "memory_enabled", False)

    listed = await c.get("/api/v1/auth/memory")
    assert listed.status_code == 200 and [m["content"] for m in listed.json()] == ["Likes tea"]
    assert (await c.delete("/api/v1/auth/memory")).status_code == 204
    assert await UserMemoryRepo(conn).list(admin.id) == []


async def test_import_works_when_memory_is_on(ctx) -> None:
    c, conn, _ws, admin = ctx
    r = await c.post("/api/v1/auth/memory/import", json={"text": "- Likes tea"})
    assert r.status_code == 200 and r.json() == {"added": 1}
