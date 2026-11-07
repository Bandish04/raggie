# SPDX-License-Identifier: Apache-2.0

"""Qdrant vector-map: api-key header and per-org scoping of scrolled points."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from embeddings_stub import CLOUD_INFO, known_profile, unknown_profile
from httpx import ASGITransport

from raggie_control_plane.api import qdrant_viz
from raggie_control_plane.api.deps import get_conn, get_current_user, get_embeddings_profile
from raggie_control_plane.config import settings
from raggie_control_plane.db.repositories import OrganizationRepo, UserRepo, WorkspaceRepo
from raggie_control_plane.embeddings_profile import EmbeddingsProfile
from raggie_control_plane.main import app
from raggie_control_plane.models import User

# Captured before any test patches httpx.AsyncClient for the app's Qdrant calls.
_RealAsyncClient = httpx.AsyncClient


@asynccontextmanager
async def _as(
    conn, user: User, profile: EmbeddingsProfile | None = None
) -> AsyncIterator[httpx.AsyncClient]:
    async def _conn_override():
        yield conn

    profile = profile or known_profile()
    app.dependency_overrides[get_conn] = _conn_override
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_embeddings_profile] = lambda: profile
    try:
        async with _RealAsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def _fake_qdrant(monkeypatch, points: list[dict]) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"result": {"points": points, "next_page_offset": None}})

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return _RealAsyncClient(*args, **kwargs)

    monkeypatch.setattr(qdrant_viz.httpx, "AsyncClient", factory)
    return seen


def _pt(ws_id, doc: str) -> dict:
    return {
        "payload": {"workspace_id": str(ws_id), "filename": doc, "document_id": doc},
        "vector": {"dense": [1.0, 0.0, float(len(doc))]},
    }


async def test_qdrant_api_key_header_sent_when_configured(conn, monkeypatch) -> None:
    org = await OrganizationRepo(conn).create("Q")
    await WorkspaceRepo(conn).create(org.id, "Q", "INTERNAL")
    su = await UserRepo(conn).create("su@q.test", "h", "SUPER_ADMIN", org_id=org.id)
    monkeypatch.setattr(settings, "qdrant_api_key", "qdrant-secret-key")
    seen = _fake_qdrant(monkeypatch, [])
    async with _as(conn, su) as c:
        assert (await c.get("/api/v1/admin/qdrant/scatter")).status_code == 200
    assert seen and seen[0].headers["api-key"] == "qdrant-secret-key"


async def test_qdrant_no_api_key_header_by_default(conn, monkeypatch) -> None:
    org = await OrganizationRepo(conn).create("Q")
    await WorkspaceRepo(conn).create(org.id, "Q", "INTERNAL")
    su = await UserRepo(conn).create("su@q.test", "h", "SUPER_ADMIN", org_id=org.id)
    monkeypatch.setattr(settings, "qdrant_api_key", "")
    seen = _fake_qdrant(monkeypatch, [])
    async with _as(conn, su) as c:
        await c.get("/api/v1/admin/qdrant/scatter")
    assert seen and "api-key" not in seen[0].headers


async def test_org_super_admin_only_sees_own_org_points(conn, monkeypatch) -> None:
    org_a = await OrganizationRepo(conn).create("A")
    org_b = await OrganizationRepo(conn).create("B")
    ws_a = await WorkspaceRepo(conn).create(org_a.id, "A", "INTERNAL")
    ws_b = await WorkspaceRepo(conn).create(org_b.id, "B", "INTERNAL")
    su_a = await UserRepo(conn).create("su@a.test", "h", "SUPER_ADMIN", org_id=org_a.id)
    _fake_qdrant(monkeypatch, [_pt(ws_a.id, "mine.pdf"), _pt(ws_b.id, "theirs-secret.pdf")])
    async with _as(conn, su_a) as c:
        body = (await c.get("/api/v1/admin/qdrant/scatter")).json()
    assert {p["filename"] for p in body["points"]} == {"mine.pdf"}


async def test_scatter_reads_the_gateway_profile_collection(conn, monkeypatch) -> None:
    org = await OrganizationRepo(conn).create("Q")
    su = await UserRepo(conn).create("su@q.test", "h", "SUPER_ADMIN", org_id=org.id)
    await WorkspaceRepo(conn).create(org.id, "Q", "INTERNAL")
    seen = _fake_qdrant(monkeypatch, [])
    async with _as(conn, su, known_profile(CLOUD_INFO)) as c:
        body = (await c.get("/api/v1/admin/qdrant/scatter")).json()
    assert body["collection"] == "raggie_chunks_d1024_5e1f00d2"
    assert seen[0].url.path == "/collections/raggie_chunks_d1024_5e1f00d2/points/scroll"


async def test_scatter_is_empty_while_no_profile_is_known(conn, monkeypatch) -> None:
    org = await OrganizationRepo(conn).create("Q")
    su = await UserRepo(conn).create("su@q.test", "h", "SUPER_ADMIN", org_id=org.id)
    seen = _fake_qdrant(monkeypatch, [])
    async with _as(conn, su, unknown_profile()) as c:
        r = await c.get("/api/v1/admin/qdrant/scatter")
    assert r.status_code == 200 and r.json()["total"] == 0 and seen == []


def _scroll_filter(request: httpx.Request) -> set[str]:
    """The workspace ids the scroll request restricts Qdrant to."""
    body = json.loads(request.content)
    (cond,) = body["filter"]["must"]
    assert cond["key"] == "workspace_id"
    return set(cond["match"]["any"])


async def test_every_scroll_page_is_filtered_to_visible_workspaces(conn, monkeypatch) -> None:
    # The collection is shared by every org: the filter goes into the Qdrant
    # request, so other tenants' points are never even loaded.
    org_a = await OrganizationRepo(conn).create("A")
    org_b = await OrganizationRepo(conn).create("B")
    ws_a1 = await WorkspaceRepo(conn).create(org_a.id, "A1", "INTERNAL")
    ws_a2 = await WorkspaceRepo(conn).create(org_a.id, "A2", "EXTERNAL")
    await WorkspaceRepo(conn).create(org_b.id, "B", "INTERNAL")
    su_a = await UserRepo(conn).create("su@a.test", "h", "SUPER_ADMIN", org_id=org_a.id)

    seen: list[httpx.Request] = []
    pages = iter(
        [
            {"points": [_pt(ws_a1.id, "one.pdf")], "next_page_offset": 7},
            {"points": [_pt(ws_a2.id, "two.pdf")], "next_page_offset": None},
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"result": next(pages)})

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return _RealAsyncClient(*args, **kwargs)

    monkeypatch.setattr(qdrant_viz.httpx, "AsyncClient", factory)
    async with _as(conn, su_a) as c:
        body = (await c.get("/api/v1/admin/qdrant/scatter")).json()

    assert len(seen) == 2
    assert all(_scroll_filter(r) == {str(ws_a1.id), str(ws_a2.id)} for r in seen)
    assert {p["filename"] for p in body["points"]} == {"one.pdf", "two.pdf"}


async def test_orgless_platform_admin_scroll_is_filtered_too(conn, monkeypatch) -> None:
    org_a = await OrganizationRepo(conn).create("A")
    org_b = await OrganizationRepo(conn).create("B")
    ws_a = await WorkspaceRepo(conn).create(org_a.id, "A", "INTERNAL")
    ws_b = await WorkspaceRepo(conn).create(org_b.id, "B", "INTERNAL")
    pa = await UserRepo(conn).create("pa@x.test", "h", "SUPER_ADMIN", is_platform_admin=True)
    seen = _fake_qdrant(monkeypatch, [])
    async with _as(conn, pa) as c:
        assert (await c.get("/api/v1/admin/qdrant/scatter")).status_code == 200
    assert seen and {str(ws_a.id), str(ws_b.id)} <= _scroll_filter(seen[0])


async def test_no_visible_workspace_sends_no_qdrant_request(conn, monkeypatch) -> None:
    org = await OrganizationRepo(conn).create("Q")
    await WorkspaceRepo(conn).create(org.id, "Q", "INTERNAL")
    wa = await UserRepo(conn).create("wa@q.test", "h", "WORKSPACE_ADMIN", org_id=org.id)
    seen = _fake_qdrant(monkeypatch, [_pt("anything", "x.pdf")])
    async with _as(conn, wa) as c:
        r = await c.get("/api/v1/admin/qdrant/scatter")
    assert r.status_code == 200 and r.json()["total"] == 0 and seen == []
