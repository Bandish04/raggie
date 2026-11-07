# SPDX-License-Identifier: Apache-2.0

"""A document deleted (or archived) while it is being ingested must never end up
with chunks in Qdrant — the KVKK/GDPR erasure guarantee cannot depend on the
ingestion and deletion lanes happening to run in a lucky order."""

from uuid import uuid4

import pytest
from qdrant_client import models

from raggie_workers.bus import RedisStreamsBus
from raggie_workers.ingestion.collection import collection_name
from raggie_workers.ingestion.consumer import IngestionConsumer
from raggie_workers.ingestion.embedder import DeterministicMockEmbedder
from raggie_workers.ingestion.objectstore import InMemoryObjectStore
from raggie_workers.ingestion.pipeline import (
    DocumentGoneError,
    DocumentJob,
    process_document,
)
from raggie_workers.ingestion.status import DocumentStatusStore
from raggie_workers.scheduler import _sweep_failed_documents
from raggie_workers.topics import DOCUMENT_FAILED, DOCUMENT_UPLOADED, INGESTION_GROUP

DIM = 8
TEXT = b"Paris is the capital of France. " * 20


async def _seed_document(pg_pool, *, status: str = "PENDING") -> tuple[str, str]:
    org_id, ws_id, doc_id = str(uuid4()), str(uuid4()), str(uuid4())
    async with pg_pool.acquire() as c:
        await c.execute("INSERT INTO organizations(id, name) VALUES($1::uuid, $2)", org_id, "Acme")
        await c.execute(
            "INSERT INTO workspaces(id, org_id, name, type) VALUES($1::uuid, $2::uuid, $3, $4)",
            ws_id,
            org_id,
            "WS",
            "INTERNAL",
        )
        await c.execute(
            "INSERT INTO documents(id, workspace_id, filename, file_size, object_key,"
            " qdrant_collection_name, status)"
            " VALUES($1::uuid, $2::uuid, $3, $4, $5, $6, $7)",
            doc_id,
            ws_id,
            "f.txt",
            100,
            f"uploads/{doc_id}.txt",
            collection_name(DIM),
            status,
        )
    return ws_id, doc_id


async def _soft_delete(pg_pool, doc_id: str) -> None:
    await pg_pool.execute("UPDATE documents SET deleted_at = now() WHERE id = $1::uuid", doc_id)


async def _point_count(qdrant_store, doc_id: str) -> int:
    collection = collection_name(DIM)
    if not await qdrant_store.client.collection_exists(collection):
        return 0
    result = await qdrant_store.client.count(
        collection_name=collection,
        count_filter=models.Filter(
            must=[models.FieldCondition(key="document_id", match=models.MatchValue(value=doc_id))]
        ),
        exact=True,
    )
    return result.count


class _DeletingEmbedder(DeterministicMockEmbedder):
    """Soft-deletes the document while its chunks are being embedded — i.e. the
    user hits delete mid-ingestion, before the upsert happens."""

    def __init__(self, dim: int, pg_pool, doc_id: str) -> None:
        super().__init__(dim)
        self._pg_pool = pg_pool
        self._doc_id = doc_id

    async def embed(self, texts: list[str]) -> list[list[float]]:
        await _soft_delete(self._pg_pool, self._doc_id)
        return await super().embed(texts)


class _DeleteDuringUpsertStore:
    """Wraps the real Qdrant store and soft-deletes the row right after the
    upsert lands — the window where a deletion cascade that already ran would
    otherwise be undone by the freshly written points."""

    def __init__(self, inner, pg_pool, doc_id: str) -> None:
        self._inner = inner
        self._pg_pool = pg_pool
        self._doc_id = doc_id

    def __getattr__(self, name):
        return getattr(self._inner, name)

    async def upsert(self, name, points) -> None:
        await self._inner.upsert(name, points)
        await _soft_delete(self._pg_pool, self._doc_id)


def _consumer(redis_client, store, vector_store, pg_pool, embedder=None) -> IngestionConsumer:
    return IngestionConsumer(
        bus=RedisStreamsBus(redis_client),
        object_store=store,
        embedder=embedder or DeterministicMockEmbedder(DIM),
        vector_store=vector_store,
        status=DocumentStatusStore(pg_pool),
    )


def _payload(ws_id: str, doc_id: str) -> dict:
    return {
        "document_id": doc_id,
        "workspace_id": ws_id,
        "filename": "f.txt",
        "object_key": f"uploads/{doc_id}.txt",
        "embedding_dim": DIM,
    }


async def test_pipeline_skips_upsert_when_document_deleted_before_upsert(
    qdrant_store, pg_pool
) -> None:
    ws_id, doc_id = await _seed_document(pg_pool)
    status = DocumentStatusStore(pg_pool)
    job = DocumentJob(document_id=doc_id, workspace_id=ws_id, filename="f.txt", embedding_dim=DIM)

    with pytest.raises(DocumentGoneError):
        await process_document(
            data=TEXT,
            job=job,
            embedder=_DeletingEmbedder(DIM, pg_pool, doc_id),
            vector_store=qdrant_store,
            is_live=lambda: status.is_live(doc_id),
        )
    assert await _point_count(qdrant_store, doc_id) == 0


async def test_pipeline_purges_points_when_deleted_during_upsert(qdrant_store, pg_pool) -> None:
    ws_id, doc_id = await _seed_document(pg_pool)
    status = DocumentStatusStore(pg_pool)
    job = DocumentJob(document_id=doc_id, workspace_id=ws_id, filename="f.txt", embedding_dim=DIM)

    with pytest.raises(DocumentGoneError):
        await process_document(
            data=TEXT,
            job=job,
            embedder=DeterministicMockEmbedder(DIM),
            vector_store=_DeleteDuringUpsertStore(qdrant_store, pg_pool, doc_id),
            is_live=lambda: status.is_live(doc_id),
        )
    assert await _point_count(qdrant_store, doc_id) == 0


async def test_consumer_leaves_no_points_for_doc_deleted_mid_ingestion(
    qdrant_store, pg_pool, redis_client
) -> None:
    ws_id, doc_id = await _seed_document(pg_pool)
    await redis_client.delete(DOCUMENT_UPLOADED, DOCUMENT_FAILED)
    store = InMemoryObjectStore()
    await store.put(f"uploads/{doc_id}.txt", TEXT)

    consumer = _consumer(
        redis_client,
        store,
        qdrant_store,
        pg_pool,
        embedder=_DeletingEmbedder(DIM, pg_pool, doc_id),
    )
    await consumer.bus.publish(DOCUMENT_UPLOADED, _payload(ws_id, doc_id))
    assert await consumer.run_once("c-race") == 1

    assert await _point_count(qdrant_store, doc_id) == 0
    # A vanished document is not an ingestion failure: no FAILED status that the
    # retry sweep would pick up, no document.failed event.
    row = await pg_pool.fetchrow("SELECT status FROM documents WHERE id = $1::uuid", doc_id)
    assert row["status"] != "FAILED"
    assert await redis_client.xlen(DOCUMENT_FAILED) == 0
    # The message is acked (nothing left pending for redelivery).
    pending = await redis_client.xpending(DOCUMENT_UPLOADED, INGESTION_GROUP)
    assert pending["pending"] == 0


async def test_consumer_skips_already_deleted_document(qdrant_store, pg_pool, redis_client) -> None:
    ws_id, doc_id = await _seed_document(pg_pool)
    await _soft_delete(pg_pool, doc_id)
    await redis_client.delete(DOCUMENT_UPLOADED, DOCUMENT_FAILED)
    store = InMemoryObjectStore()
    await store.put(f"uploads/{doc_id}.txt", TEXT)

    consumer = _consumer(redis_client, store, qdrant_store, pg_pool)
    await consumer.bus.publish(DOCUMENT_UPLOADED, _payload(ws_id, doc_id))
    assert await consumer.run_once("c-race") == 1

    assert await _point_count(qdrant_store, doc_id) == 0
    row = await pg_pool.fetchrow("SELECT status FROM documents WHERE id = $1::uuid", doc_id)
    assert row["status"] == "PENDING"  # untouched: not PROCESSING, not FAILED
    assert await redis_client.xlen(DOCUMENT_FAILED) == 0


async def test_consumer_skips_archived_document_and_keeps_archived_status(
    qdrant_store, pg_pool, redis_client
) -> None:
    ws_id, doc_id = await _seed_document(pg_pool, status="ARCHIVED")
    await pg_pool.execute("UPDATE documents SET archived_at = now() WHERE id = $1::uuid", doc_id)
    await redis_client.delete(DOCUMENT_UPLOADED, DOCUMENT_FAILED)
    store = InMemoryObjectStore()
    await store.put(f"uploads/{doc_id}.txt", TEXT)

    consumer = _consumer(redis_client, store, qdrant_store, pg_pool)
    await consumer.bus.publish(DOCUMENT_UPLOADED, _payload(ws_id, doc_id))
    assert await consumer.run_once("c-race") == 1

    assert await _point_count(qdrant_store, doc_id) == 0
    row = await pg_pool.fetchrow("SELECT status FROM documents WHERE id = $1::uuid", doc_id)
    assert row["status"] == "ARCHIVED"


async def test_status_writes_never_touch_deleted_documents(pg_pool) -> None:
    _ws_id, doc_id = await _seed_document(pg_pool)
    await _soft_delete(pg_pool, doc_id)
    status = DocumentStatusStore(pg_pool)

    await status.mark_processing(doc_id)
    await status.mark_success(doc_id)
    await status.mark_failed(doc_id, "boom")

    row = await pg_pool.fetchrow(
        "SELECT status, error_message FROM documents WHERE id = $1::uuid", doc_id
    )
    assert row["status"] == "PENDING"
    assert row["error_message"] is None
    assert await status.is_live(doc_id) is False


class _RecordingBus:
    def __init__(self) -> None:
        self.published: list[dict] = []

    async def publish(self, _topic: str, payload: dict) -> None:
        self.published.append(payload)


async def test_retry_sweep_skips_deleted_and_archived_documents(pg_pool) -> None:
    _ws, deleted_id = await _seed_document(pg_pool, status="FAILED")
    await _soft_delete(pg_pool, deleted_id)
    _ws, archived_id = await _seed_document(pg_pool, status="FAILED")
    await pg_pool.execute(
        "UPDATE documents SET archived_at = now() WHERE id = $1::uuid", archived_id
    )
    _ws, live_id = await _seed_document(pg_pool, status="FAILED")

    bus = _RecordingBus()
    # Drain every retryable FAILED doc (other tests may have left some behind).
    while await _sweep_failed_documents(pg_pool, bus):
        pass

    retried = {p["document_id"] for p in bus.published}
    assert live_id in retried
    assert deleted_id not in retried
    assert archived_id not in retried
    rows = await pg_pool.fetch(
        "SELECT id::text, status, retry_count FROM documents WHERE id = ANY($1::uuid[])",
        [deleted_id, archived_id],
    )
    assert all(r["status"] == "FAILED" and r["retry_count"] == 0 for r in rows)
