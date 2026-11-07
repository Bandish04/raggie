# SPDX-License-Identifier: Apache-2.0

"""Admin embeddings API (status card + re-embed) and the ingest gate on every
document intake route."""

from __future__ import annotations

import json
from uuid import uuid4

import asyncpg
import httpx
import pytest_asyncio
from embeddings_stub import CLOUD_INFO, LEGACY_INFO, known_profile, unknown_profile
from httpx import ASGITransport

from raggie_control_plane.api.deps import (
    get_conn,
    get_current_user,
    get_embeddings_profile,
    get_event_publisher,
    get_object_store,
)
from raggie_control_plane.config import settings
from raggie_control_plane.db.migrate import apply_migrations
from raggie_control_plane.db.repositories import (
    DocumentRepo,
    OrganizationRepo,
    UserRepo,
    WorkspaceRepo,
)
from raggie_control_plane.embeddings_profile import EmbeddingsProfile
from raggie_control_plane.infra.objectstore import InMemoryObjectStore
from raggie_control_plane.main import app

A = "/api/v1/admin"


class RecordingPublisher:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def publish(self, topic: str, payload: dict) -> str:
        self.events.append((topic, payload))
        return "1-0"


class Harness:
    def __init__(self, client, store, publisher, conn, user) -> None:
        self.client = client
        self.store = store
        self.publisher = publisher
        self.conn = conn
        self.user = user
        self.profile: EmbeddingsProfile = known_profile()


@pytest_asyncio.fixture
async def h(conn):
    # Start from "no profile accepted yet": a lifespan-backed test that ran
    # earlier (the `client` fixture) commits the gateway profile at app boot.
    # Rolled back with the test, like everything below.
    await conn.execute(
        "UPDATE system_settings SET embedding_fingerprint = NULL, embedding_profile = NULL"
        " WHERE id = 'current'"
    )
    await conn.execute("UPDATE documents SET deleted_at = now() WHERE deleted_at IS NULL")
    await conn.execute("UPDATE users SET is_platform_admin = FALSE WHERE is_platform_admin")
    org = await OrganizationRepo(conn).create("Platform")
    pa = await UserRepo(conn).create(
        f"pa-{uuid4().hex[:8]}@raggie.test",
        "h",
        "SUPER_ADMIN",
        org_id=org.id,
        is_platform_admin=True,
    )
    store, publisher = InMemoryObjectStore(), RecordingPublisher()
    harness = Harness(None, store, publisher, conn, pa)

    async def _conn_override():
        yield conn

    app.dependency_overrides[get_conn] = _conn_override
    app.dependency_overrides[get_current_user] = lambda: harness.user
    app.dependency_overrides[get_object_store] = lambda: store
    app.dependency_overrides[get_event_publisher] = lambda: publisher
    app.dependency_overrides[get_embeddings_profile] = lambda: harness.profile
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        harness.client = c
        yield harness
    app.dependency_overrides.clear()


async def _accept(conn, fingerprint: str | None, profile: dict | None = None) -> None:
    await conn.execute("INSERT INTO system_settings(id) VALUES('current') ON CONFLICT DO NOTHING")
    await conn.execute(
        "UPDATE system_settings SET embedding_fingerprint = $1, embedding_profile = $2::jsonb"
        " WHERE id='current'",
        fingerprint,
        profile,
    )


async def _mismatched(conn, policy: str = "block_ingest") -> EmbeddingsProfile:
    """The gateway moved to the cloud profile while the platform's documents
    are still indexed under the accepted legacy one."""
    await _accept(conn, LEGACY_INFO["fingerprint"], LEGACY_INFO)
    await _legacy_doc(conn, await _ws(conn, "Indexed"), "indexed.pdf")
    profile = known_profile(CLOUD_INFO, policy=policy)
    await profile.evaluate(conn)
    assert profile.mismatch
    return profile


async def _legacy_doc(conn, ws, name: str = "a.pdf", **kw):
    return await DocumentRepo(conn).create(
        ws.id,
        name,
        1,
        "raggie_chunks_d1024",
        object_key=f"uploads/{ws.id}/{name}",
        embedding_fingerprint="2872ae6a",
        **kw,
    )


async def _ws(conn, name: str = "Docs"):
    org = await OrganizationRepo(conn).create(f"Org {name}")
    return await WorkspaceRepo(conn).create(org.id, name, "INTERNAL")


# ── Ingest gate ───────────────────────────────────────────────────────────────


async def test_upload_targets_the_gateway_collection_and_records_fingerprint(h) -> None:
    h.profile = known_profile(CLOUD_INFO)
    await _accept(h.conn, CLOUD_INFO["fingerprint"])
    ws = await _ws(h.conn)

    r = await h.client.post(
        f"{A}/workspaces/{ws.id}/documents",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )

    assert r.status_code == 201
    body = r.json()
    assert body["qdrant_collection_name"] == "raggie_chunks_d1024_5e1f00d2"
    assert body["embedding_fingerprint"] == "5e1f00d2"
    [(topic, payload)] = h.publisher.events
    assert topic == "raggie.document.uploaded"
    assert payload["collection"] == "raggie_chunks_d1024_5e1f00d2"
    assert payload["embedding_fingerprint"] == "5e1f00d2"
    assert payload["embedding_dim"] == 1024


async def test_upload_is_refused_with_409_on_fingerprint_mismatch(h) -> None:
    h.profile = await _mismatched(h.conn)
    ws = await _ws(h.conn)

    r = await h.client.post(
        f"{A}/workspaces/{ws.id}/documents",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )

    assert r.status_code == 409
    assert "re-embed" in r.json()["detail"].lower()
    assert h.publisher.events == [] and h.store._store == {}


async def test_upload_is_refused_with_503_while_the_profile_is_unknown(h) -> None:
    h.profile = unknown_profile()
    ws = await _ws(h.conn)

    r = await h.client.post(
        f"{A}/workspaces/{ws.id}/documents",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )

    assert r.status_code == 503 and r.headers["retry-after"]
    assert h.publisher.events == []


async def test_multipart_upload_is_gated_at_create_and_complete(h) -> None:
    ws = await _ws(h.conn)
    created = await h.client.post(
        f"{A}/workspaces/{ws.id}/documents/uploads",
        json={"filename": "big.pdf", "size": 10},
    )
    assert created.status_code == 200
    h.profile = await _mismatched(h.conn)

    assert (
        await h.client.post(f"{A}/workspaces/{ws.id}/documents/uploads", json={"filename": "x.pdf"})
    ).status_code == 409
    completed = await h.client.post(
        f"{A}/workspaces/{ws.id}/documents/uploads/complete",
        json={
            "upload_id": created.json()["upload_id"],
            "object_key": created.json()["object_key"],
            "filename": "big.pdf",
            "parts": [{"part_number": 1, "etag": "e"}],
        },
    )
    assert completed.status_code == 409
    assert h.publisher.events == []


async def test_reindex_and_retry_use_the_gateway_profile(h) -> None:
    h.profile = known_profile(CLOUD_INFO)
    await _accept(h.conn, CLOUD_INFO["fingerprint"])
    ws = await _ws(h.conn)
    doc = await _legacy_doc(h.conn, ws)
    failed = await _legacy_doc(h.conn, ws, "f.pdf")
    await h.conn.execute("UPDATE documents SET status = 'FAILED' WHERE id = $1", failed.id)

    r = await h.client.post(f"{A}/workspaces/{ws.id}/documents/reindex")
    assert r.status_code == 200 and r.json() == {"reindexed": 2, "skipped": 0}
    assert {p["collection"] for _t, p in h.publisher.events} == {"raggie_chunks_d1024_5e1f00d2"}

    await h.conn.execute("UPDATE documents SET status = 'FAILED' WHERE id = $1", failed.id)
    h.publisher.events.clear()
    r = await h.client.post(f"{A}/documents/retry-failed")
    assert r.status_code == 200 and r.json() == {"retried": 1}
    [(_topic, payload)] = h.publisher.events
    assert payload["document_id"] == str(failed.id)
    assert payload["embedding_fingerprint"] == "5e1f00d2"
    assert (await DocumentRepo(h.conn).get(doc.id)).embedding_fingerprint == "5e1f00d2"


async def test_reindex_routes_are_gated_on_mismatch(h) -> None:
    h.profile = await _mismatched(h.conn)
    ws = await _ws(h.conn)
    await _legacy_doc(h.conn, ws)
    for path in (
        f"{A}/workspaces/{ws.id}/documents/reindex",
        f"{A}/documents/reindex-all",
        f"{A}/documents/retry-failed",
    ):
        assert (await h.client.post(path)).status_code == 409, path
    assert h.publisher.events == []


# ── GET /admin/embeddings ─────────────────────────────────────────────────────


async def test_status_reports_profile_counts_and_mismatch(h) -> None:
    h.profile = await _mismatched(h.conn)  # + one legacy document
    ws = await _ws(h.conn)
    await _legacy_doc(h.conn, ws, "a.pdf")
    await DocumentRepo(h.conn).create(ws.id, "old.pdf", 1, "raggie_chunks_d384")

    r = await h.client.get(f"{A}/embeddings")

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "mismatch" and body["mismatch"] is True
    assert body["ingest_blocked"] is True and "re-embed" in body["detail"].lower()
    assert body["policy"] == "block_ingest"
    assert body["stored_fingerprint"] == "2872ae6a"
    assert body["profile"] == {k: v for k, v in CLOUD_INFO.items() if k != "some_future_field"}
    assert body["documents"] == [
        {"fingerprint": "2872ae6a", "count": 2},
        {"fingerprint": None, "count": 1},
    ]
    assert body["reembed"] == {
        "target_fingerprint": "5e1f00d2",
        "total": 0,  # nothing indexed under the new profile yet
        "completed": 0,
        "pending": 0,
        "processing": 0,
        "failed": 0,
        "stale": 3,
        "in_progress": False,
        "last_started_at": None,
    }


async def test_status_when_the_gateway_was_never_reached(h, gateway) -> None:
    gateway.routes["info"].mock(side_effect=httpx.ConnectError("refused"))
    h.profile = unknown_profile()
    body = (await h.client.get(f"{A}/embeddings")).json()
    assert body["status"] == "unknown" and body["profile"] is None
    assert body["ingest_blocked"] is True
    assert body["gateway_error"] == "embeddings gateway unreachable (ConnectError)"
    assert body["documents"] == [] and body["reembed"]["target_fingerprint"] is None


@pytest_asyncio.fixture
async def committed_profile():
    """What a lifespan-backed test (the ``client`` fixture) leaves behind: the app
    boot stores the gateway profile through the real pool, committed, outside
    any test transaction. Restored afterwards."""
    c = await asyncpg.connect(settings.dsn)
    try:
        await apply_migrations(c, settings.migrations_dir)
        await c.execute("INSERT INTO system_settings(id) VALUES('current') ON CONFLICT DO NOTHING")
        before = await c.fetchrow(
            "SELECT embedding_fingerprint, embedding_profile FROM system_settings"
            " WHERE id='current'"
        )
        await c.execute(
            "UPDATE system_settings SET embedding_fingerprint = $1, embedding_profile = $2::jsonb"
            " WHERE id='current'",
            LEGACY_INFO["fingerprint"],
            json.dumps(LEGACY_INFO),  # a plain connection: no JSON codec
        )
        yield
        await c.execute(
            "UPDATE system_settings SET embedding_fingerprint = $1, embedding_profile = $2::jsonb"
            " WHERE id='current'",
            before["embedding_fingerprint"],
            before["embedding_profile"],
        )
    finally:
        await c.close()


async def test_never_reached_is_independent_of_earlier_tests(committed_profile, h, gateway) -> None:
    """Regression: run after a lifespan-backed test, the platform already had a
    committed accepted profile, and the "never reached" status saw it."""
    await test_status_when_the_gateway_was_never_reached(h, gateway)


async def test_status_picks_up_a_gateway_change_within_the_ttl(h, gateway) -> None:
    """The card reads /info through the TTL cache, so a reconfigured gateway shows
    up (as a mismatch when documents exist) before the next background check."""
    await _accept(h.conn, "2872ae6a", LEGACY_INFO)
    ws = await _ws(h.conn)
    await _legacy_doc(h.conn, ws)
    gateway.routes["info"].respond(json=CLOUD_INFO)
    h.profile = known_profile()
    h.profile.client._fetched_at -= 3600  # cache expired

    body = (await h.client.get(f"{A}/embeddings")).json()

    assert body["profile"]["fingerprint"] == "5e1f00d2"
    assert body["mismatch"] is True and body["ingest_blocked"] is True


async def test_status_and_reembed_are_platform_admin_only(h) -> None:
    h.user = h.user.model_copy(update={"is_platform_admin": False})
    assert (await h.client.get(f"{A}/embeddings")).status_code == 403
    r = await h.client.post(f"{A}/embeddings/reembed", json={"fingerprint": "5e1f00d2"})
    assert r.status_code == 403


# ── POST /admin/embeddings/reembed ────────────────────────────────────────────


async def test_reembed_moves_every_live_document_to_the_new_collection(h, gateway) -> None:
    await _accept(h.conn, "2872ae6a", LEGACY_INFO)
    gateway.routes["info"].respond(json=CLOUD_INFO)
    ws_a, ws_b = await _ws(h.conn, "A"), await _ws(h.conn, "B")
    a = await _legacy_doc(h.conn, ws_a)
    b = await _legacy_doc(h.conn, ws_b)
    gone = await _legacy_doc(h.conn, ws_b, "gone.pdf")
    await DocumentRepo(h.conn).soft_delete(gone.id)
    h.profile = known_profile(CLOUD_INFO)
    await h.profile.evaluate(h.conn)
    assert h.profile.mismatch

    r = await h.client.post(f"{A}/embeddings/reembed", json={"fingerprint": "5e1f00d2"})

    assert r.status_code == 200
    out = r.json()
    assert out["fingerprint"] == "5e1f00d2"
    assert out["collection"] == "raggie_chunks_d1024_5e1f00d2"
    assert out["reembedded"] == 2 and out["skipped"] == 0
    assert {p["document_id"] for _t, p in h.publisher.events} == {str(a.id), str(b.id)}
    assert all(
        p["collection"] == "raggie_chunks_d1024_5e1f00d2"
        and p["embedding_fingerprint"] == "5e1f00d2"
        for _t, p in h.publisher.events
    )
    stored = await h.conn.fetchval(
        "SELECT embedding_fingerprint FROM system_settings WHERE id='current'"
    )
    assert stored == "5e1f00d2"
    assert h.profile.mismatch is False

    status = (await h.client.get(f"{A}/embeddings")).json()
    assert status["status"] == "ok" and status["ingest_blocked"] is False
    assert status["reembed"]["pending"] == 2 and status["reembed"]["in_progress"] is True
    assert status["reembed"]["last_started_at"] is not None

    started = await h.conn.fetchrow(
        "SELECT actor_user_id, metadata FROM audit_log WHERE action = 'embedding.reembed_started'"
        " AND created_at >= now()"
    )
    assert started["actor_user_id"] == h.user.id
    assert started["metadata"]["trigger"] == "admin"

    # Uploads flow again, into the new collection.
    upload = await h.client.post(
        f"{A}/workspaces/{ws_a.id}/documents",
        files={"file": ("n.txt", b"x", "text/plain")},
    )
    assert upload.status_code == 201
    assert upload.json()["qdrant_collection_name"] == "raggie_chunks_d1024_5e1f00d2"


async def test_reembed_refuses_a_stale_confirmation(h, gateway) -> None:
    """The admin confirmed the profile they saw; if the gateway changed since,
    nothing is re-embedded (a re-embed can cost real money in cloud mode)."""
    gateway.routes["info"].respond(json=CLOUD_INFO)
    h.profile = await _mismatched(h.conn)
    ws = await _ws(h.conn)
    await _legacy_doc(h.conn, ws)

    r = await h.client.post(f"{A}/embeddings/reembed", json={"fingerprint": "2872ae6a"})

    assert r.status_code == 409 and "5e1f00d2" in r.json()["detail"]
    assert h.publisher.events == []


async def test_reembed_needs_a_reachable_gateway(h, gateway) -> None:
    gateway.routes["info"].mock(side_effect=httpx.ConnectError("refused"))
    r = await h.client.post(f"{A}/embeddings/reembed", json={"fingerprint": "5e1f00d2"})
    assert r.status_code == 503


async def test_reembed_validates_the_fingerprint(h) -> None:
    r = await h.client.post(f"{A}/embeddings/reembed", json={"fingerprint": "nope"})
    assert r.status_code == 422
