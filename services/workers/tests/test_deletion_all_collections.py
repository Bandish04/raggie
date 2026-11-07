# SPDX-License-Identifier: Apache-2.0

"""KVKK: deleting (or archiving) a document must remove its chunks, and their
plain-text payload, from EVERY Raggie collection. After an embedding-profile
change and a re-embed, the old collection still holds the document. Runs on
qdrant-client's in-process local mode (no server)."""

from __future__ import annotations

import uuid

import pytest
from qdrant_client import AsyncQdrantClient, models

from raggie_workers.ingestion.deletion import DeletionConsumer
from raggie_workers.ingestion.objectstore import InMemoryObjectStore
from raggie_workers.ingestion.vectorstore import ChunkPoint, QdrantVectorStore

pytestmark = pytest.mark.filterwarnings("ignore:Payload indexes have no effect")

OLD = "raggie_chunks_d4"  # legacy profile
NEW = "raggie_chunks_d4_abcd1234"  # after an embedding-profile change + re-embed
FOREIGN = "someone_elses_collection"  # same Qdrant, not ours: never touched
DOC, OTHER_DOC = str(uuid.uuid4()), str(uuid.uuid4())
WS, OTHER_WS = str(uuid.uuid4()), str(uuid.uuid4())


async def _store() -> QdrantVectorStore:
    store = QdrantVectorStore(AsyncQdrantClient(location=":memory:"))
    for name in (OLD, NEW, FOREIGN):
        await store.ensure_collection(name, 4)
    return store


async def _seed(store: QdrantVectorStore, name: str, doc: str, ws: str, n: int = 2) -> None:
    await store.upsert(
        name,
        [
            ChunkPoint(
                id=str(uuid.uuid4()),
                dense=[0.1, 0.2, 0.3, 0.4],
                payload={
                    "document_id": doc,
                    "workspace_id": ws,
                    "chunk_index": i,
                    "text": f"secret text {i}",
                },
            )
            for i in range(n)
        ],
    )


async def _count(store: QdrantVectorStore, name: str, doc: str, ws: str | None = None) -> int:
    must = [models.FieldCondition(key="document_id", match=models.MatchValue(value=doc))]
    if ws:
        must.append(models.FieldCondition(key="workspace_id", match=models.MatchValue(value=ws)))
    resp = await store.client.count(name, count_filter=models.Filter(must=must), exact=True)
    return resp.count


def _consumer(store: QdrantVectorStore) -> DeletionConsumer:
    return DeletionConsumer(bus=None, object_store=InMemoryObjectStore(), vector_store=store)


def _event(**overrides) -> dict:
    event = {
        "document_id": DOC,
        "workspace_id": WS,
        "collection": NEW,
        "object_key": f"uploads/{DOC}.pdf",
        "purge_object": True,
    }
    event.update(overrides)
    return event


@pytest.mark.parametrize("purge_object", [True, False], ids=["delete", "archive"])
async def test_document_is_purged_from_every_raggie_collection(purge_object) -> None:
    store = await _store()
    for name in (OLD, NEW):
        await _seed(store, name, DOC, WS)
        await _seed(store, name, OTHER_DOC, WS)  # a neighbour that must survive

    await _consumer(store).handle(_event(purge_object=purge_object))

    assert await _count(store, OLD, DOC) == 0
    assert await _count(store, NEW, DOC) == 0
    assert await _count(store, OLD, OTHER_DOC) == 2
    assert await _count(store, NEW, OTHER_DOC) == 2


async def test_purge_is_scoped_to_the_workspace_and_to_raggie_collections() -> None:
    store = await _store()
    await _seed(store, OLD, DOC, WS)
    await _seed(store, OLD, DOC, OTHER_WS)  # same id under another tenant: not ours to delete
    await _seed(store, FOREIGN, DOC, WS)  # not a Raggie collection

    await _consumer(store).handle(_event())

    assert await _count(store, OLD, DOC, WS) == 0
    assert await _count(store, OLD, DOC, OTHER_WS) == 2
    assert await _count(store, FOREIGN, DOC, WS) == 2


async def test_purge_is_idempotent() -> None:
    store = await _store()
    await _seed(store, OLD, DOC, WS)
    consumer = _consumer(store)
    await consumer.handle(_event())
    await consumer.handle(_event())  # redelivery: nothing left, no error
    assert await _count(store, OLD, DOC) == 0


async def test_pinned_collection_missing_is_fine() -> None:
    store = await _store()
    await _seed(store, OLD, DOC, WS)
    await _consumer(store).handle(_event(collection="raggie_chunks_d8"))  # never created
    assert await _count(store, OLD, DOC) == 0


async def test_legacy_event_without_workspace_purges_only_the_pinned_collection() -> None:
    # No workspace_id: a cross-collection purge can't be tenant-scoped, so only
    # the collection the event names is purged (the pre-fix behaviour).
    store = await _store()
    await _seed(store, OLD, DOC, WS)
    await _seed(store, NEW, DOC, WS)
    event = _event(collection=NEW)
    del event["workspace_id"]
    await _consumer(store).handle(event)
    assert await _count(store, NEW, DOC) == 0
    assert await _count(store, OLD, DOC) == 2


class _RacingClient:
    """Lists a collection that is dropped before the delete reaches it."""

    def __init__(self, status: int) -> None:
        self.status = status

    async def get_collections(self):
        return models.CollectionsResponse(collections=[models.CollectionDescription(name=OLD)])

    async def delete(self, **_kwargs):
        import httpx
        from qdrant_client.http.exceptions import UnexpectedResponse

        raise UnexpectedResponse(
            status_code=self.status, reason_phrase="x", content=b"", headers=httpx.Headers()
        )


async def test_collection_dropped_mid_purge_is_ignored_but_other_errors_propagate() -> None:
    from qdrant_client.http.exceptions import UnexpectedResponse

    assert await QdrantVectorStore(_RacingClient(404)).purge_document(DOC, WS) == [OLD]
    with pytest.raises(UnexpectedResponse):  # keeps the event pending for a retry
        await QdrantVectorStore(_RacingClient(503)).purge_document(DOC, WS)
