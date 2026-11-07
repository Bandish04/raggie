# SPDX-License-Identifier: Apache-2.0

from uuid import uuid4

import pytest

from raggie_workers.bus import RedisStreamsBus
from raggie_workers.ingestion.collection import collection_name
from raggie_workers.ingestion.deletion import DeletionConsumer
from raggie_workers.ingestion.embedder import DeterministicMockEmbedder
from raggie_workers.ingestion.objectstore import InMemoryObjectStore
from raggie_workers.ingestion.vectorstore import ChunkPoint
from raggie_workers.topics import DOCUMENT_DELETED, INGESTION_GROUP

DIM = 8


async def _seed_chunks(qdrant_store, ws_id: str, document_id: str, n: int = 3) -> str:
    collection = collection_name(DIM)
    await qdrant_store.ensure_collection(collection, DIM)
    vectors = await DeterministicMockEmbedder(DIM).embed([f"chunk {i}" for i in range(n)])
    points = [
        ChunkPoint(
            id=str(uuid4()),
            dense=vectors[i],
            payload={
                "workspace_id": ws_id,
                "document_id": document_id,
                "chunk_index": i,
                "text": f"chunk {i}",
            },
        )
        for i in range(n)
    ]
    await qdrant_store.upsert(collection, points)
    return collection


def _consumer(redis_client, object_store, qdrant_store) -> DeletionConsumer:
    return DeletionConsumer(
        bus=RedisStreamsBus(redis_client),
        object_store=object_store,
        vector_store=qdrant_store,
    )


async def test_archive_drops_qdrant_chunks_but_keeps_object(qdrant_store, redis_client) -> None:
    ws_id, doc_id = str(uuid4()), str(uuid4())
    collection = await _seed_chunks(qdrant_store, ws_id, doc_id)
    await redis_client.delete(DOCUMENT_DELETED)

    store = InMemoryObjectStore()
    key = f"uploads/{doc_id}.txt"
    await store.put(key, b"raw bytes")

    consumer = _consumer(redis_client, store, qdrant_store)
    await consumer.bus.publish(
        DOCUMENT_DELETED,
        {
            "document_id": doc_id,
            "workspace_id": ws_id,
            "object_key": key,
            "collection": collection,
            "purge_object": False,  # archive: keep the object
        },
    )
    assert await consumer.run_once("d-test") == 1

    # Qdrant chunks for this document are gone.
    qvec = (await DeterministicMockEmbedder(DIM).embed(["chunk 0"]))[0]
    hits = await qdrant_store.search(collection, qvec, ws_id, k=10)
    assert all(h.get("document_id") != doc_id for h in hits)
    # The raw object is preserved (archive is reversible).
    assert await store.get(key) == b"raw bytes"


async def test_delete_purges_qdrant_chunks_and_object(qdrant_store, redis_client) -> None:
    ws_id, doc_id = str(uuid4()), str(uuid4())
    collection = await _seed_chunks(qdrant_store, ws_id, doc_id)
    await redis_client.delete(DOCUMENT_DELETED)

    store = InMemoryObjectStore()
    key = f"uploads/{doc_id}.txt"
    await store.put(key, b"raw bytes")

    consumer = _consumer(redis_client, store, qdrant_store)
    await consumer.bus.publish(
        DOCUMENT_DELETED,
        {
            "document_id": doc_id,
            "workspace_id": ws_id,
            "object_key": key,
            "collection": collection,
            "purge_object": True,  # delete: hard-remove the object too
        },
    )
    assert await consumer.run_once("d-test") == 1

    qvec = (await DeterministicMockEmbedder(DIM).embed(["chunk 0"]))[0]
    hits = await qdrant_store.search(collection, qvec, ws_id, k=10)
    assert all(h.get("document_id") != doc_id for h in hits)
    # The object is hard-deleted.
    with pytest.raises(KeyError):
        await store.get(key)


async def test_delete_is_idempotent_and_fail_soft(qdrant_store, redis_client) -> None:
    """A document with no chunks / a missing collection / an absent object must
    not raise — re-delivery is a safe no-op."""
    ws_id, doc_id = str(uuid4()), str(uuid4())
    await redis_client.delete(DOCUMENT_DELETED)

    store = InMemoryObjectStore()
    consumer = _consumer(redis_client, store, qdrant_store)
    await consumer.bus.publish(
        DOCUMENT_DELETED,
        {
            "document_id": doc_id,
            "workspace_id": ws_id,
            "object_key": f"uploads/{doc_id}.txt",  # never put -> absent
            "collection": collection_name(DIM),
            "purge_object": True,
        },
    )
    # No exception, message acked.
    assert await consumer.run_once("d-test") == 1


async def test_delete_failure_stays_pending_for_retry(redis_client) -> None:
    class FailingVectorStore:
        async def purge_document(self, _document_id: str, _workspace_id: str) -> list[str]:
            raise RuntimeError("qdrant unavailable")

    await redis_client.delete(DOCUMENT_DELETED)
    consumer = DeletionConsumer(
        bus=RedisStreamsBus(redis_client),
        object_store=InMemoryObjectStore(),
        vector_store=FailingVectorStore(),
    )
    await consumer.bus.publish(
        DOCUMENT_DELETED,
        {
            "document_id": str(uuid4()),
            "workspace_id": str(uuid4()),
            "collection": collection_name(DIM),
            "purge_object": False,
        },
    )

    assert await consumer.run_once("failing-worker") == 1
    pending = await redis_client.xpending(DOCUMENT_DELETED, INGESTION_GROUP)
    assert pending["pending"] == 1
