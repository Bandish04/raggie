# SPDX-License-Identifier: Apache-2.0

"""Embedding profile: the gateway /info client, boot-time reconciliation with
the indexed documents, the ingest gate and readiness."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import httpx
import pytest
from embeddings_stub import CLOUD_INFO, LEGACY_INFO, known_profile
from fastapi.testclient import TestClient

from raggie_control_plane import embeddings_profile as ep
from raggie_control_plane.config import settings
from raggie_control_plane.db.repositories import DocumentRepo, OrganizationRepo, WorkspaceRepo
from raggie_control_plane.embeddings_profile import (
    EmbeddingsProfile,
    GatewayInfoClient,
    GatewayUnavailableError,
    IngestBlockedError,
)
from raggie_control_plane.main import app

BASE = settings.embeddings_base_url


class RecordingPublisher:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def publish(self, topic: str, payload: dict) -> str:
        self.events.append((topic, payload))
        return "1-0"


class OnePool:
    """Just enough of asyncpg.Pool for EmbeddingsProfile.refresh."""

    def __init__(self, conn) -> None:
        self.conn = conn

    @asynccontextmanager
    async def acquire(self):
        yield self.conn


async def _fresh_platform(conn, *, stored: str | None = None, profile: dict | None = None):
    """Hide every pre-existing document and set the accepted fingerprint, all
    inside the test's rolled-back transaction."""
    await conn.execute("UPDATE documents SET deleted_at = now() WHERE deleted_at IS NULL")
    await conn.execute("INSERT INTO system_settings(id) VALUES('current') ON CONFLICT DO NOTHING")
    await conn.execute(
        "UPDATE system_settings SET embedding_fingerprint = $1, embedding_profile = $2::jsonb"
        " WHERE id='current'",
        stored,
        profile,
    )


async def _workspace(conn, name: str = "Docs"):
    org = await OrganizationRepo(conn).create(f"Acme {name}")
    return await WorkspaceRepo(conn).create(org.id, name, "INTERNAL")


async def _stored(conn) -> tuple[str | None, dict | None]:
    row = await conn.fetchrow(
        "SELECT embedding_fingerprint, embedding_profile FROM system_settings WHERE id='current'"
    )
    return row["embedding_fingerprint"], row["embedding_profile"]


async def _audits(conn, action: str) -> list[dict]:
    rows = await conn.fetch(
        "SELECT metadata, actor_user_id FROM audit_log WHERE action = $1"
        " AND created_at >= now() ORDER BY created_at",  # now() = this transaction
        action,
    )
    return [dict(r) for r in rows]


def _profile(**kwargs) -> EmbeddingsProfile:
    return EmbeddingsProfile(GatewayInfoClient(BASE), **kwargs)


# ── /v1/info client ───────────────────────────────────────────────────────────


async def test_info_client_sends_internal_bearer_and_caches_for_ttl(gateway) -> None:
    now = [100.0]
    client = GatewayInfoClient(BASE, secret="s" * 40, ttl_seconds=60, clock=lambda: now[0])

    first = await client.get()
    again = await client.get()
    assert first.fingerprint == again.fingerprint == "2872ae6a"
    assert gateway.routes["info"].call_count == 1
    request = gateway.routes["info"].calls.last.request
    assert request.headers["authorization"] == "Bearer " + "s" * 40

    now[0] += 61
    await client.get()
    assert gateway.routes["info"].call_count == 2
    await client.get(force=True)
    assert gateway.routes["info"].call_count == 3


async def test_info_client_without_secret_sends_no_authorization(gateway) -> None:
    await GatewayInfoClient(BASE).get()
    assert "authorization" not in gateway.routes["info"].calls.last.request.headers


async def test_info_client_ignores_unknown_fields(gateway) -> None:
    gateway.routes["info"].respond(json=CLOUD_INFO)
    info = await GatewayInfoClient(BASE).get()
    assert info.collection == "raggie_chunks_d1024_5e1f00d2"
    assert info.egress.dense_host == "api.openai.com"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(503, json={"detail": "loading"}),
        httpx.Response(401, json={"detail": "unauthorized"}),
        httpx.Response(200, text="not json"),
        # A collection outside the contract never reaches a Qdrant URL path.
        httpx.Response(200, json={**LEGACY_INFO, "collection": "../../collections/x"}),
        httpx.Response(200, json={**LEGACY_INFO, "fingerprint": "XYZ"}),
    ],
)
async def test_info_client_rejects_bad_answers(gateway, response) -> None:
    gateway.routes["info"].mock(return_value=response)
    with pytest.raises(GatewayUnavailableError):
        await GatewayInfoClient(BASE).get()


async def test_info_client_unreachable_gateway(gateway) -> None:
    gateway.routes["info"].mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(GatewayUnavailableError, match="unreachable"):
        await GatewayInfoClient(BASE, secret="t" * 40).get()


# ── Reconciliation ────────────────────────────────────────────────────────────


async def test_first_boot_stores_fingerprint_and_profile_and_audits(conn, gateway) -> None:
    await _fresh_platform(conn)
    profile = _profile()

    await profile.reconcile(conn, RecordingPublisher())

    fingerprint, stored_profile = await _stored(conn)
    assert fingerprint == "2872ae6a"
    assert stored_profile["collection"] == "raggie_chunks_d1024"
    assert profile.mismatch is False and profile.status == "ok"
    target = await profile.ingest_target(conn)
    assert (target.collection, target.fingerprint, target.dim) == (
        "raggie_chunks_d1024",
        "2872ae6a",
        1024,
    )
    [audit] = await _audits(conn, "embedding.profile_changed")
    meta = audit["metadata"]
    assert meta["reason"] == "initial" and meta["previous_fingerprint"] is None
    assert meta["provider"] == "local" and meta["model"] == "intfloat/multilingual-e5-large"
    assert meta["dense_host"] is None and meta["rerank_host"] is None


async def test_unchanged_profile_is_a_noop(conn, gateway) -> None:
    profile = _profile()
    await _fresh_platform(conn)
    await profile.reconcile(conn, RecordingPublisher())
    await profile.reconcile(conn, RecordingPublisher())
    assert len(await _audits(conn, "embedding.profile_changed")) == 1


async def test_egress_change_without_new_fingerprint_is_audited(conn, gateway) -> None:
    """Moving the upstream behind a proxy keeps the vectors (same fingerprint)
    but changes where document text goes: the profile is re-stored and audited."""
    await _fresh_platform(conn)
    gateway.routes["info"].respond(json=CLOUD_INFO)
    profile = _profile()
    await profile.reconcile(conn, RecordingPublisher())

    moved = {**CLOUD_INFO, "egress": {"dense_host": "llm-proxy.corp", "rerank_host": None}}
    gateway.routes["info"].respond(json=moved)
    await profile.reconcile(conn, RecordingPublisher())

    fingerprint, stored_profile = await _stored(conn)
    assert fingerprint == CLOUD_INFO["fingerprint"]
    assert stored_profile["egress"] == {"dense_host": "llm-proxy.corp", "rerank_host": None}
    audits = await _audits(conn, "embedding.profile_changed")
    assert [a["metadata"]["reason"] for a in audits] == ["initial", "profile_updated"]
    assert audits[-1]["metadata"]["dense_host"] == "llm-proxy.corp"
    assert "api_key" not in str(audits[-1]["metadata"]).lower()


async def test_new_profile_without_indexed_documents_is_adopted(conn, gateway) -> None:
    await _fresh_platform(conn, stored="2872ae6a", profile=LEGACY_INFO)
    ws = await _workspace(conn)
    await DocumentRepo(conn).create(
        ws.id, "gone.pdf", 1, "raggie_chunks_d1024", embedding_fingerprint="2872ae6a"
    )
    await conn.execute("UPDATE documents SET archived_at = now() WHERE workspace_id = $1", ws.id)
    gateway.routes["info"].respond(json=CLOUD_INFO)
    profile = _profile()

    await profile.reconcile(conn, RecordingPublisher())

    assert (await _stored(conn))[0] == CLOUD_INFO["fingerprint"]
    assert profile.mismatch is False
    [audit] = await _audits(conn, "embedding.profile_changed")
    assert audit["metadata"]["reason"] == "adopted"
    assert audit["metadata"]["previous_fingerprint"] == "2872ae6a"
    assert audit["metadata"]["dense_host"] == "api.openai.com"


async def test_mismatch_with_indexed_documents_blocks_ingest(conn, gateway) -> None:
    await _fresh_platform(conn, stored="2872ae6a", profile=LEGACY_INFO)
    ws = await _workspace(conn)
    await DocumentRepo(conn).create(
        ws.id, "a.pdf", 1, "raggie_chunks_d1024", object_key="k", embedding_fingerprint="2872ae6a"
    )
    gateway.routes["info"].respond(json=CLOUD_INFO)
    publisher = RecordingPublisher()
    profile = _profile()

    await profile.reconcile(conn, publisher)

    assert (await _stored(conn))[0] == "2872ae6a"  # never silently re-pointed
    assert profile.mismatch is True and profile.status == "mismatch"
    with pytest.raises(IngestBlockedError) as blocked:
        await profile.ingest_target(conn)
    assert blocked.value.status_code == 409
    assert CLOUD_INFO["fingerprint"] in blocked.value.detail
    assert "re-embed" in blocked.value.detail.lower()
    assert profile.readiness() == (
        200,
        {"status": "degraded", "embeddings": "fingerprint_mismatch"},
    )
    assert publisher.events == []
    assert await _audits(conn, "embedding.profile_changed") == []


async def test_legacy_documents_without_fingerprint_count_as_stale(conn, gateway) -> None:
    """Rows from before 0026 outside the legacy collection carry no fingerprint;
    they are in no collection the gateway serves, so they block like any other."""
    await _fresh_platform(conn)
    ws = await _workspace(conn)
    await DocumentRepo(conn).create(ws.id, "old.pdf", 1, "raggie_chunks_d384", object_key="k")
    profile = _profile()
    await profile.reconcile(conn, RecordingPublisher())
    assert profile.mismatch is True
    assert (await _stored(conn))[0] is None


async def test_refuse_boot_policy_fails_readiness(conn, gateway) -> None:
    await _fresh_platform(conn, stored="2872ae6a", profile=LEGACY_INFO)
    ws = await _workspace(conn)
    await DocumentRepo(conn).create(
        ws.id, "a.pdf", 1, "raggie_chunks_d1024", embedding_fingerprint="2872ae6a"
    )
    gateway.routes["info"].respond(json=CLOUD_INFO)
    profile = _profile(policy="refuse_boot")

    await profile.reconcile(conn, RecordingPublisher())

    status_code, body = profile.readiness()
    assert status_code == 503 and body["embeddings"] == "fingerprint_mismatch"


async def test_auto_reindex_without_confirmation_only_blocks(conn, gateway) -> None:
    await _fresh_platform(conn, stored="2872ae6a", profile=LEGACY_INFO)
    ws = await _workspace(conn)
    await DocumentRepo(conn).create(
        ws.id, "a.pdf", 1, "raggie_chunks_d1024", object_key="k", embedding_fingerprint="2872ae6a"
    )
    gateway.routes["info"].respond(json=CLOUD_INFO)
    publisher = RecordingPublisher()
    # A confirmation for some other fingerprint is not a confirmation.
    profile = _profile(policy="auto_reindex", reembed_confirm="2872ae6a")

    await profile.reconcile(conn, publisher)

    assert profile.mismatch is True and publisher.events == []
    assert (await _stored(conn))[0] == "2872ae6a"


async def test_auto_reindex_with_confirmation_reembeds_into_new_collection(conn, gateway) -> None:
    await _fresh_platform(conn, stored="2872ae6a", profile=LEGACY_INFO)
    ws = await _workspace(conn)
    docs = DocumentRepo(conn)
    live = await docs.create(
        ws.id,
        "a.pdf",
        1,
        "raggie_chunks_d1024",
        object_key=f"uploads/{ws.id}/a.pdf",
        embedding_fingerprint="2872ae6a",
    )
    no_raw = await docs.create(
        ws.id, "b.pdf", 1, "raggie_chunks_d1024", embedding_fingerprint="2872ae6a"
    )
    archived = await docs.create(
        ws.id,
        "c.pdf",
        1,
        "raggie_chunks_d1024",
        object_key=f"uploads/{ws.id}/c.pdf",
        embedding_fingerprint="2872ae6a",
    )
    await docs.archive(archived.id)
    gateway.routes["info"].respond(json=CLOUD_INFO)
    publisher = RecordingPublisher()
    profile = _profile(policy="auto_reindex", reembed_confirm=CLOUD_INFO["fingerprint"])

    await profile.reconcile(conn, publisher)

    assert (await _stored(conn))[0] == CLOUD_INFO["fingerprint"]
    assert profile.mismatch is False
    assert publisher.events == [
        (
            "raggie.document.uploaded",
            {
                "document_id": str(live.id),
                "workspace_id": str(ws.id),
                "filename": "a.pdf",
                "object_key": f"uploads/{ws.id}/a.pdf",
                "embedding_dim": 1024,
                "collection": "raggie_chunks_d1024_5e1f00d2",
                "embedding_fingerprint": "5e1f00d2",
            },
        )
    ]
    row = await conn.fetchrow(
        "SELECT status, qdrant_collection_name, embedding_fingerprint FROM documents WHERE id = $1",
        live.id,
    )
    assert dict(row) == {
        "status": "PENDING",
        "qdrant_collection_name": "raggie_chunks_d1024_5e1f00d2",
        "embedding_fingerprint": "5e1f00d2",
    }
    untouched = await conn.fetchval(
        "SELECT embedding_fingerprint FROM documents WHERE id = $1", archived.id
    )
    assert untouched == "2872ae6a"
    assert (await docs.get(no_raw.id)).embedding_fingerprint == "2872ae6a"  # skipped
    [started] = await _audits(conn, "embedding.reembed_started")
    assert started["metadata"]["trigger"] == "auto_reindex"
    assert started["metadata"]["reembedded"] == 1 and started["metadata"]["skipped"] == 1
    assert started["actor_user_id"] is None
    [changed] = await _audits(conn, "embedding.profile_changed")
    assert changed["metadata"]["reason"] == "auto_reindex"

    # Resumable and idempotent: a second pass re-publishes nothing.
    await profile.reconcile(conn, publisher)
    assert len(publisher.events) == 1


async def test_gateway_down_leaves_profile_unknown_and_blocks_ingest(conn, gateway) -> None:
    gateway.routes["info"].mock(side_effect=httpx.ConnectError("refused"))
    profile = _profile()

    assert await profile.refresh(OnePool(conn), RecordingPublisher()) is False

    assert profile.info is None and profile.status == "unknown"
    assert "unreachable" in profile.last_error
    with pytest.raises(IngestBlockedError) as blocked:
        await profile.ingest_target(conn)
    assert blocked.value.status_code == 503 and blocked.value.retry_after
    assert profile.readiness() == (200, {"status": "degraded", "embeddings": "profile_unknown"})


async def test_gateway_outage_after_boot_keeps_the_last_known_profile(conn, gateway) -> None:
    await _fresh_platform(conn)
    profile = _profile()
    assert await profile.refresh(OnePool(conn), RecordingPublisher()) is True

    gateway.routes["info"].mock(side_effect=httpx.ConnectError("refused"))
    assert await profile.refresh(OnePool(conn), RecordingPublisher()) is False

    assert (await profile.ingest_target(conn)).fingerprint == "2872ae6a"
    assert profile.readiness() == (200, {"status": "ready"})


async def test_run_retries_with_backoff_until_the_gateway_answers(monkeypatch) -> None:
    profile = _profile(refresh_seconds=60)
    outcomes = iter([False, False, True, False, False])
    sleeps: list[float] = []

    async def fake_refresh(pool, publisher) -> bool:
        return next(outcomes)

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) == 5:
            raise asyncio.CancelledError

    monkeypatch.setattr(profile, "refresh", fake_refresh)
    monkeypatch.setattr(ep.asyncio, "sleep", fake_sleep)
    with pytest.raises(asyncio.CancelledError):
        await profile.run(None, None)
    assert sleeps == [2.0, 4.0, 8.0, 60, 2.0]


async def test_mismatch_clears_as_soon_as_another_replica_reembedded(conn, gateway) -> None:
    await _fresh_platform(conn, stored="2872ae6a", profile=LEGACY_INFO)
    ws = await _workspace(conn)
    await DocumentRepo(conn).create(
        ws.id, "a.pdf", 1, "raggie_chunks_d1024", object_key="k", embedding_fingerprint="2872ae6a"
    )
    gateway.routes["info"].respond(json=CLOUD_INFO)
    profile = _profile()
    await profile.reconcile(conn, RecordingPublisher())
    assert profile.mismatch

    # Another replica accepted the new profile (POST /admin/embeddings/reembed).
    await conn.execute(
        "UPDATE system_settings SET embedding_fingerprint = $1 WHERE id='current'",
        CLOUD_INFO["fingerprint"],
    )
    assert (await profile.ingest_target(conn)).fingerprint == CLOUD_INFO["fingerprint"]


# ── Wiring: lifespan + /readyz ────────────────────────────────────────────────


@pytest.mark.requires_postgres  # runs the app lifespan inline (no `client` fixture)
@pytest.mark.requires_redis
def test_boot_with_the_gateway_down_still_serves(gateway) -> None:
    gateway.routes["info"].mock(side_effect=httpx.ConnectError("refused"))
    with TestClient(app) as c:
        assert c.get("/healthz").status_code == 200
        r = c.get("/readyz")
        assert r.status_code == 200
        assert r.json() == {"status": "degraded", "embeddings": "profile_unknown"}
        assert app.state.embeddings_profile.info is None


def test_boot_reconciles_the_gateway_profile(client) -> None:
    profile = app.state.embeddings_profile
    assert profile.info is not None and profile.info.fingerprint == "2872ae6a"
    assert profile.checked_at is not None


def test_readyz_refuse_boot_mismatch_is_503(client, monkeypatch) -> None:
    profile = known_profile(CLOUD_INFO, policy="refuse_boot")
    profile.mismatch = True
    monkeypatch.setattr(app.state, "embeddings_profile", profile)
    r = client.get("/readyz")
    assert r.status_code == 503
    assert r.json()["embeddings"] == "fingerprint_mismatch"


def test_readyz_block_ingest_mismatch_stays_in_rotation(client, monkeypatch) -> None:
    profile = known_profile(CLOUD_INFO)
    profile.mismatch = True
    monkeypatch.setattr(app.state, "embeddings_profile", profile)
    r = client.get("/readyz")
    assert r.status_code == 200
    assert r.json() == {"status": "degraded", "embeddings": "fingerprint_mismatch"}
