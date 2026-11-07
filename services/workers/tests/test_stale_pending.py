# SPDX-License-Identifier: Apache-2.0

"""Stale-PENDING sweep: an upload event lost in a Redis/Valkey failover (async
replication) must not leave a document PENDING forever."""

import asyncio
from uuid import uuid4

import pytest

import raggie_workers.ingestion.consumer as consumer_module
from raggie_workers.config import Settings
from raggie_workers.ingestion.consumer import IngestionConsumer
from raggie_workers.ingestion.pipeline import IngestResult
from raggie_workers.scheduler import STALE_REPUBLISHED, _sweep_stale_pending

DIM = 8


class _Bus:
    def __init__(self) -> None:
        self.published: list[dict] = []

    async def publish(self, _topic, payload) -> None:
        self.published.append(payload)


async def _seed(
    pg_pool,
    *,
    status: str,
    age_seconds: int,
    deleted: bool = False,
    archived: bool = False,
    object_key: bool = True,
    fingerprint: str | None = "abcd1234",
) -> str:
    org_id, ws_id, doc_id = str(uuid4()), str(uuid4()), str(uuid4())
    async with pg_pool.acquire() as c:
        await c.execute("INSERT INTO organizations(id, name) VALUES($1::uuid, 'A')", org_id)
        await c.execute(
            "INSERT INTO workspaces(id, org_id, name, type)"
            " VALUES($1::uuid, $2::uuid, 'W', 'INTERNAL')",
            ws_id,
            org_id,
        )
        # INSERT (not UPDATE) so the set_updated_at trigger keeps our backdated value.
        await c.execute(
            "INSERT INTO documents(id, workspace_id, filename, file_size, object_key,"
            " qdrant_collection_name, status, embedding_fingerprint, updated_at,"
            " deleted_at, archived_at)"
            " VALUES($1::uuid, $2::uuid, 'f.txt', 1, $3, $4, $5, $6,"
            " now() - make_interval(secs => $7),"
            " CASE WHEN $8 THEN now() END, CASE WHEN $9 THEN now() END)",
            doc_id,
            ws_id,
            f"uploads/{doc_id}.txt" if object_key else None,
            f"raggie_chunks_d{DIM}_abcd1234",
            status,
            fingerprint,
            age_seconds,
            deleted,
            archived,
        )
    return doc_id


async def _drain(pg_pool, bus, **kw) -> set[str]:
    while await _sweep_stale_pending(pg_pool, bus, **kw):
        pass
    return {p["document_id"] for p in bus.published}


async def test_stale_live_pending_and_processing_are_republished(pg_pool) -> None:
    pending = await _seed(pg_pool, status="PENDING", age_seconds=3600)
    processing = await _seed(pg_pool, status="PROCESSING", age_seconds=3600)
    bus = _Bus()
    before = STALE_REPUBLISHED._value.get()

    republished = await _drain(pg_pool, bus, stale_seconds=900, batch=50)

    assert {pending, processing} <= republished
    payload = next(p for p in bus.published if p["document_id"] == pending)
    assert payload["collection"] == f"raggie_chunks_d{DIM}_abcd1234"
    assert payload["embedding_fingerprint"] == "abcd1234"
    assert payload["embedding_dim"] == DIM
    assert payload["object_key"] == f"uploads/{pending}.txt"
    rows = await pg_pool.fetch(
        "SELECT status, updated_at > now() - interval '1 minute' AS touched"
        " FROM documents WHERE id = ANY($1::uuid[])",
        [pending, processing],
    )
    assert all(r["status"] == "PENDING" and r["touched"] for r in rows)
    assert STALE_REPUBLISHED._value.get() - before >= 2


async def test_fresh_removed_terminal_and_objectless_docs_are_left_alone(pg_pool) -> None:
    skipped = [
        await _seed(pg_pool, status="PENDING", age_seconds=60),  # fresh
        await _seed(pg_pool, status="PENDING", age_seconds=3600, deleted=True),
        await _seed(pg_pool, status="PENDING", age_seconds=3600, archived=True),
        await _seed(pg_pool, status="SUCCESS", age_seconds=3600),
        await _seed(pg_pool, status="FAILED", age_seconds=3600),
        await _seed(pg_pool, status="PENDING", age_seconds=3600, object_key=False),
    ]
    republished = await _drain(pg_pool, _Bus(), stale_seconds=900, batch=50)
    assert not set(skipped) & republished


async def test_a_republished_doc_is_not_picked_again_next_tick(pg_pool) -> None:
    doc = await _seed(pg_pool, status="PENDING", age_seconds=3600)
    await _drain(pg_pool, _Bus(), stale_seconds=900, batch=50)
    again = _Bus()
    await _sweep_stale_pending(pg_pool, again, stale_seconds=900, batch=50)
    assert doc not in {p["document_id"] for p in again.published}


async def test_sweep_is_bounded_per_tick(pg_pool) -> None:
    for _ in range(3):
        await _seed(pg_pool, status="PENDING", age_seconds=7200)
    bus = _Bus()
    assert await _sweep_stale_pending(pg_pool, bus, stale_seconds=900, batch=2) <= 2


# ─────────────────────────── infra-free unit tests ─────────────────────────


def test_stale_pending_knobs(monkeypatch) -> None:
    monkeypatch.delenv("STALE_PENDING_SECONDS", raising=False)
    monkeypatch.delenv("INGEST_HEARTBEAT_SECONDS", raising=False)
    cfg = Settings(_env_file=None)
    assert (cfg.stale_pending_seconds, cfg.stale_pending_batch, cfg.ingest_heartbeat_seconds) == (
        900,
        50,
        60,
    )
    monkeypatch.setenv("STALE_PENDING_SECONDS", "300")
    monkeypatch.setenv("INGEST_HEARTBEAT_SECONDS", "20")
    cfg = Settings(_env_file=None)
    assert (cfg.stale_pending_seconds, cfg.ingest_heartbeat_seconds) == (300, 20)


def test_heartbeat_must_be_shorter_than_staleness() -> None:
    with pytest.raises(ValueError, match="INGEST_HEARTBEAT_SECONDS"):
        Settings(_env_file=None, stale_pending_seconds=60, ingest_heartbeat_seconds=60)


class _Status:
    def __init__(self) -> None:
        self.touches = 0
        self.events: list[str] = []

    async def is_live(self, _doc_id) -> bool:
        return True

    async def mark_processing(self, _doc_id) -> None:
        self.events.append("processing")

    async def touch(self, _doc_id) -> None:
        self.touches += 1

    async def mark_success(self, _doc_id, _fp=None) -> None:
        self.events.append("success")

    async def mark_failed(self, _doc_id, _err, *, terminal=False) -> None:
        self.events.append("failed")


class _Store:
    async def download_to_file(self, _key, _path) -> None:
        return None


async def test_consumer_heartbeats_while_processing(monkeypatch) -> None:
    async def slow_process(**_kw):
        await asyncio.sleep(0.35)
        return IngestResult(document_id="d", collection="c", chunks=1)

    monkeypatch.setattr(consumer_module, "process_document", slow_process)
    status = _Status()
    consumer = IngestionConsumer(
        bus=_Bus(),
        object_store=_Store(),
        embedder=None,
        vector_store=None,
        status=status,
        heartbeat_seconds=0.1,
    )
    await consumer.handle(
        {
            "document_id": "d",
            "workspace_id": "w",
            "filename": "f.txt",
            "object_key": "k",
            "embedding_dim": DIM,
        }
    )
    assert status.touches >= 2
    assert status.events == ["processing", "success"]
    await asyncio.sleep(0.25)
    touches = status.touches
    await asyncio.sleep(0.25)
    assert status.touches == touches  # heartbeat stops with the document


async def test_consumer_passes_the_configured_embed_batch_size(monkeypatch) -> None:
    seen = {}

    async def capture(**kwargs):
        seen.update(kwargs)
        return IngestResult(document_id="d", collection="c", chunks=1)

    monkeypatch.setattr(consumer_module, "process_document", capture)
    consumer = IngestionConsumer(
        bus=_Bus(),
        object_store=_Store(),
        embedder=None,
        vector_store=None,
        status=_Status(),
        embed_batch_size=16,
    )
    await consumer.handle(
        {
            "document_id": "d",
            "workspace_id": "w",
            "filename": "f.txt",
            "object_key": "k",
            "embedding_dim": DIM,
        }
    )
    assert seen["batch_size"] == 16
