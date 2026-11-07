# SPDX-License-Identifier: Apache-2.0

"""Phase 2.3: the workers follow the gateway's embedding profile — collection
from the event (or gateway), fingerprint checks, HA collection parameters."""

from uuid import uuid4

import pytest
from qdrant_client import AsyncQdrantClient, models

from raggie_workers.bus import RedisStreamsBus
from raggie_workers.config import Settings
from raggie_workers.ingestion.consumer import IngestionConsumer
from raggie_workers.ingestion.embedder import DeterministicMockEmbedder
from raggie_workers.ingestion.objectstore import InMemoryObjectStore
from raggie_workers.ingestion.openai_embedder import EmbedResult, FingerprintMismatch
from raggie_workers.ingestion.pipeline import DocumentJob, process_document
from raggie_workers.ingestion.status import DocumentStatusStore
from raggie_workers.ingestion.vectorstore import QdrantVectorStore
from raggie_workers.scheduler import _sweep_failed_documents
from raggie_workers.topics import DOCUMENT_FAILED, DOCUMENT_UPLOADED

DIM = 8
TEXT = b"The leave policy grants fourteen days. " * 10


class ProfileEmbedder(DeterministicMockEmbedder):
    """Gateway-like embedder that reports a profile fingerprint/collection."""

    def __init__(self, dim: int, fingerprint: str | None, collection: str | None) -> None:
        super().__init__(dim)
        self.fingerprint = fingerprint
        self.collection = collection

    async def embed_with_profile(self, texts, *, expected_fingerprint=None):
        if expected_fingerprint and self.fingerprint and expected_fingerprint != self.fingerprint:
            raise FingerprintMismatch(expected_fingerprint, self.fingerprint)
        return EmbedResult(await self.embed(texts), self.fingerprint, self.collection)


async def _count(store: QdrantVectorStore, collection: str, doc_id: str) -> int:
    if not await store.client.collection_exists(collection):
        return 0
    flt = models.Filter(
        must=[models.FieldCondition(key="document_id", match=models.MatchValue(value=doc_id))]
    )
    return (await store.client.count(collection, count_filter=flt, exact=True)).count


@pytest.fixture
async def temp_collections(qdrant_store):
    """Random per-test collection names, dropped afterwards (keeps the shared
    test Qdrant small across runs)."""
    names: list[str] = []

    def make() -> str:
        names.append(f"raggie_chunks_d{DIM}_{uuid4().hex[:8]}")
        return names[-1]

    yield make
    for name in names:
        if await qdrant_store.client.collection_exists(name):
            await qdrant_store.client.delete_collection(name)


def _job(**kw) -> DocumentJob:
    base = dict(
        document_id=str(uuid4()), workspace_id=str(uuid4()), filename="f.txt", embedding_dim=DIM
    )
    base.update(kw)
    return DocumentJob(**base)


async def test_event_collection_takes_precedence(qdrant_store, temp_collections) -> None:
    target = temp_collections()
    job = _job(collection=target)
    result = await process_document(
        data=TEXT,
        job=job,
        vector_store=qdrant_store,
        embedder=ProfileEmbedder(DIM, "abcd1234", temp_collections()),
    )
    assert result.collection == target
    assert await _count(qdrant_store, target, job.document_id) > 0
    assert result.fingerprint == "abcd1234"


async def test_gateway_collection_beats_dim_derived_name(qdrant_store, temp_collections) -> None:
    gateway_collection = temp_collections()
    job = _job()
    result = await process_document(
        data=TEXT,
        job=job,
        vector_store=qdrant_store,
        embedder=ProfileEmbedder(DIM, "abcd1234", gateway_collection),
    )
    assert result.collection == gateway_collection
    assert await _count(qdrant_store, f"raggie_chunks_d{DIM}", job.document_id) == 0


async def test_legacy_embedder_still_uses_dim_derived_collection(qdrant_store) -> None:
    result = await process_document(
        data=TEXT, job=_job(), vector_store=qdrant_store, embedder=DeterministicMockEmbedder(DIM)
    )
    assert result.collection == f"raggie_chunks_d{DIM}" and result.fingerprint is None


async def test_fingerprint_mismatch_indexes_nothing(qdrant_store, temp_collections) -> None:
    job = _job(collection=temp_collections(), embedding_fingerprint="aaaa1111")
    with pytest.raises(FingerprintMismatch):
        await process_document(
            data=TEXT,
            job=job,
            vector_store=qdrant_store,
            embedder=ProfileEmbedder(DIM, "bbbb2222", None),
        )
    assert await _count(qdrant_store, job.collection, job.document_id) == 0


@pytest.mark.requires_qdrant  # builds its own client (no qdrant_store fixture)
async def test_new_collections_use_ha_parameters() -> None:
    import os

    client = AsyncQdrantClient(url=os.environ["QDRANT_TEST_URL"])
    try:
        store = QdrantVectorStore(
            client, replication_factor=1, shard_number=2, write_consistency_factor=1
        )
        name = f"raggie_chunks_d{DIM}_{uuid4().hex[:8]}"
        await store.ensure_collection(name, DIM)
        params = (await client.get_collection(name)).config.params
        assert (
            params.shard_number,
            params.replication_factor,
            params.write_consistency_factor,
        ) == (2, 1, 1)
        await client.delete_collection(name)
    finally:
        await client.close()


def test_ha_and_embed_knobs_from_env(monkeypatch) -> None:
    for key, value in {
        "QDRANT_REPLICATION_FACTOR": "3",
        "QDRANT_SHARD_NUMBER": "6",
        "QDRANT_WRITE_CONSISTENCY_FACTOR": "2",
        "EMBED_TIMEOUT_SECONDS": "90",
        "EMBED_MAX_RETRIES": "4",
    }.items():
        monkeypatch.setenv(key, value)
    cfg = Settings(_env_file=None)
    assert (
        cfg.qdrant_replication_factor,
        cfg.qdrant_shard_number,
        cfg.qdrant_write_consistency_factor,
    ) == (3, 6, 2)
    assert (cfg.embed_timeout_seconds, cfg.embed_max_retries) == (90, 4)


def test_ha_and_embed_defaults(monkeypatch) -> None:
    for key in (
        "QDRANT_REPLICATION_FACTOR",
        "QDRANT_SHARD_NUMBER",
        "QDRANT_WRITE_CONSISTENCY_FACTOR",
        "EMBED_TIMEOUT_SECONDS",
        "EMBED_MAX_RETRIES",
    ):
        monkeypatch.delenv(key, raising=False)
    cfg = Settings(_env_file=None)
    assert (
        cfg.qdrant_replication_factor,
        cfg.qdrant_shard_number,
        cfg.qdrant_write_consistency_factor,
    ) == (1, 1, 1)
    assert (cfg.embed_timeout_seconds, cfg.embed_max_retries) == (180, 6)


# ───────────────────────────── consumer + status ───────────────────────────


async def _seed(
    pg_pool, *, fingerprint: str | None = None, status: str = "PENDING"
) -> tuple[str, str]:
    org_id, ws_id, doc_id = str(uuid4()), str(uuid4()), str(uuid4())
    async with pg_pool.acquire() as c:
        await c.execute("INSERT INTO organizations(id, name) VALUES($1::uuid, $2)", org_id, "A")
        await c.execute(
            "INSERT INTO workspaces(id, org_id, name, type)"
            " VALUES($1::uuid, $2::uuid, 'W', 'INTERNAL')",
            ws_id,
            org_id,
        )
        await c.execute(
            "INSERT INTO documents(id, workspace_id, filename, file_size, object_key,"
            " qdrant_collection_name, status, embedding_fingerprint)"
            " VALUES($1::uuid, $2::uuid, 'f.txt', 1, $3, $4, $5, $6)",
            doc_id,
            ws_id,
            f"uploads/{doc_id}.txt",
            f"raggie_chunks_d{DIM}_abcd1234",
            status,
            fingerprint,
        )
    return ws_id, doc_id


def _consumer(redis_client, store, qdrant_store, pg_pool, embedder) -> IngestionConsumer:
    return IngestionConsumer(
        bus=RedisStreamsBus(redis_client),
        object_store=store,
        embedder=embedder,
        vector_store=qdrant_store,
        status=DocumentStatusStore(pg_pool),
    )


async def _publish(consumer, ws_id, doc_id, **extra) -> None:
    await consumer.bus.publish(
        DOCUMENT_UPLOADED,
        {
            "document_id": doc_id,
            "workspace_id": ws_id,
            "filename": "f.txt",
            "object_key": f"uploads/{doc_id}.txt",
            "embedding_dim": DIM,
            **extra,
        },
    )


async def test_success_records_the_gateway_fingerprint(
    qdrant_store, pg_pool, redis_client, temp_collections
) -> None:
    ws_id, doc_id = await _seed(pg_pool)
    await redis_client.delete(DOCUMENT_UPLOADED)
    store = InMemoryObjectStore()
    await store.put(f"uploads/{doc_id}.txt", TEXT)
    collection = temp_collections()
    consumer = _consumer(
        redis_client, store, qdrant_store, pg_pool, ProfileEmbedder(DIM, "abcd1234", collection)
    )
    await _publish(consumer, ws_id, doc_id, collection=collection)
    assert await consumer.run_once("c-fp") == 1
    row = await pg_pool.fetchrow(
        "SELECT status, embedding_fingerprint FROM documents WHERE id = $1::uuid", doc_id
    )
    assert (row["status"], row["embedding_fingerprint"]) == ("SUCCESS", "abcd1234")


async def test_mismatch_fails_terminally(qdrant_store, pg_pool, redis_client) -> None:
    ws_id, doc_id = await _seed(pg_pool, fingerprint="aaaa1111")
    await redis_client.delete(DOCUMENT_UPLOADED, DOCUMENT_FAILED)
    store = InMemoryObjectStore()
    await store.put(f"uploads/{doc_id}.txt", TEXT)
    consumer = _consumer(
        redis_client, store, qdrant_store, pg_pool, ProfileEmbedder(DIM, "bbbb2222", None)
    )
    await _publish(
        consumer,
        ws_id,
        doc_id,
        embedding_fingerprint="aaaa1111",
        collection=f"raggie_chunks_d{DIM}_aaaa1111",
    )
    await consumer.run_once("c-fp")
    row = await pg_pool.fetchrow(
        "SELECT status, error_message, retry_count, max_retries FROM documents WHERE id = $1::uuid",
        doc_id,
    )
    assert row["status"] == "FAILED"
    assert "re-embed" in row["error_message"] or "!=" in row["error_message"]
    assert row["retry_count"] >= row["max_retries"]  # the retry sweep never picks it up


class _Bus:
    def __init__(self) -> None:
        self.published: list[dict] = []

    async def publish(self, _topic, payload) -> None:
        self.published.append(payload)


async def test_retry_sweep_republishes_collection_and_fingerprint(pg_pool) -> None:
    _ws, doc_id = await _seed(pg_pool, fingerprint="abcd1234", status="FAILED")
    bus = _Bus()
    while await _sweep_failed_documents(pg_pool, bus):
        pass
    payload = next(p for p in bus.published if p["document_id"] == doc_id)
    assert payload["collection"] == f"raggie_chunks_d{DIM}_abcd1234"
    assert payload["embedding_fingerprint"] == "abcd1234"
    assert payload["embedding_dim"] == DIM
