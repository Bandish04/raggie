# SPDX-License-Identifier: Apache-2.0

from uuid import uuid4

from raggie_workers.bus import RedisStreamsBus
from raggie_workers.ingestion.collection import collection_name
from raggie_workers.ingestion.consumer import IngestionConsumer
from raggie_workers.ingestion.embedder import DeterministicMockEmbedder
from raggie_workers.ingestion.objectstore import InMemoryObjectStore
from raggie_workers.ingestion.status import DocumentStatusStore
from raggie_workers.topics import DOCUMENT_UPLOADED

DIM = 8


async def _seed_document(pg_pool) -> tuple[str, str, str]:
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
            "INSERT INTO documents(id, workspace_id, filename, file_size,"
            " qdrant_collection_name, status) VALUES($1::uuid, $2::uuid, $3, $4, $5, 'PENDING')",
            doc_id,
            ws_id,
            "f.txt",
            100,
            collection_name(DIM),
        )
    return org_id, ws_id, doc_id


def _consumer(redis_client, store, qdrant_store, pg_pool) -> IngestionConsumer:
    return IngestionConsumer(
        bus=RedisStreamsBus(redis_client),
        object_store=store,
        embedder=DeterministicMockEmbedder(DIM),
        vector_store=qdrant_store,
        status=DocumentStatusStore(pg_pool),
    )


async def test_consumer_processes_and_marks_success(qdrant_store, pg_pool, redis_client) -> None:
    _org, ws_id, doc_id = await _seed_document(pg_pool)
    await redis_client.delete(DOCUMENT_UPLOADED)

    store = InMemoryObjectStore()
    key = f"uploads/{doc_id}.txt"
    await store.put(key, b"Paris is the capital of France.")

    consumer = _consumer(redis_client, store, qdrant_store, pg_pool)
    await consumer.bus.publish(
        DOCUMENT_UPLOADED,
        {
            "document_id": doc_id,
            "workspace_id": ws_id,
            "filename": "f.txt",
            "object_key": key,
            "embedding_dim": DIM,
        },
    )
    assert await consumer.run_once("c-test") == 1

    row = await pg_pool.fetchrow("SELECT status FROM documents WHERE id = $1::uuid", doc_id)
    assert row["status"] == "SUCCESS"

    qvec = (await DeterministicMockEmbedder(DIM).embed(["Paris is the capital of France."]))[0]
    hits = await qdrant_store.search(collection_name(DIM), qvec, ws_id, k=4)
    assert hits


async def test_consumer_marks_failed_on_missing_object(qdrant_store, pg_pool, redis_client) -> None:
    _org, ws_id, doc_id = await _seed_document(pg_pool)
    await redis_client.delete(DOCUMENT_UPLOADED)

    consumer = _consumer(redis_client, InMemoryObjectStore(), qdrant_store, pg_pool)
    await consumer.bus.publish(
        DOCUMENT_UPLOADED,
        {
            "document_id": doc_id,
            "workspace_id": ws_id,
            "filename": "f.txt",
            "object_key": "does-not-exist",
            "embedding_dim": DIM,
        },
    )
    await consumer.run_once("c-test")

    row = await pg_pool.fetchrow(
        "SELECT status, error_message FROM documents WHERE id = $1::uuid", doc_id
    )
    assert row["status"] == "FAILED"
    assert row["error_message"] == "The uploaded file could not be read from object storage."


async def test_consumer_marks_over_limit_document_failed_with_reason(
    qdrant_store, pg_pool, redis_client
) -> None:
    import io

    from reportlab.pdfgen import canvas

    from raggie_workers.ingestion.parsing import ParserLimits

    _org, ws_id, doc_id = await _seed_document(pg_pool)
    await redis_client.delete(DOCUMENT_UPLOADED)
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    for i in range(3):
        c.drawString(54, 700, f"Page {i} carries enough text to skip the OCR fallback.")
        c.showPage()
    c.save()
    store = InMemoryObjectStore()
    key = f"uploads/{doc_id}.pdf"
    await store.put(key, buf.getvalue())

    consumer = _consumer(redis_client, store, qdrant_store, pg_pool)
    consumer.parser_limits = ParserLimits(max_pdf_pages=2)
    await consumer.bus.publish(
        DOCUMENT_UPLOADED,
        {
            "document_id": doc_id,
            "workspace_id": ws_id,
            "filename": "big.pdf",
            "object_key": key,
            "embedding_dim": DIM,
        },
    )
    assert await consumer.run_once("c-test") == 1

    row = await pg_pool.fetchrow(
        "SELECT status, error_message FROM documents WHERE id = $1::uuid", doc_id
    )
    assert row["status"] == "FAILED"
    assert row["error_message"] == "PDF has more than 2 pages."
