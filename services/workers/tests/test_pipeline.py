# SPDX-License-Identifier: Apache-2.0

import io
import time
from uuid import uuid4

import parse_helpers
import pytest

import raggie_workers.ingestion.pipeline as pipeline_module
from raggie_workers.ingestion.embedder import DeterministicMockEmbedder
from raggie_workers.ingestion.pipeline import DocumentJob, process_document


class _CapturingVectorStore:
    def __init__(self) -> None:
        self.points = []
        self.collection = ""

    async def ensure_collection(self, name: str, _dim: int) -> None:
        self.collection = name

    async def upsert(self, _name: str, points: list) -> None:
        self.points.extend(points)

    async def delete_stale_document_chunks(
        self, _name: str, _document_id: str, _keep_count: int
    ) -> None:
        return None


def _make_pdf(pages: list[str]) -> bytes:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    for page in pages:
        y = 740
        for line in page.split("\n"):
            c.drawString(54, y, line[:110])
            y -= 13
            if y < 54:
                break
        c.showPage()
    c.save()
    return buf.getvalue()


def _make_xlsx() -> bytes:
    import openpyxl

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "SLA Matrix"
    sheet.append(["Tier", "Resolution target"])
    sheet.append(["Critical", "4 hours"])
    buf = io.BytesIO()
    workbook.save(buf)
    workbook.close()
    return buf.getvalue()


async def test_ingest_then_search_is_workspace_isolated(qdrant_store) -> None:
    dim = 8
    embedder = DeterministicMockEmbedder(dim)
    workspace_id = str(uuid4())
    data = _make_pdf(["The capital of France is Paris.", "Raggie ingests documents."])
    job = DocumentJob(
        document_id=str(uuid4()),
        workspace_id=workspace_id,
        filename="facts.pdf",
        embedding_dim=dim,
    )

    result = await process_document(
        data=data, job=job, embedder=embedder, vector_store=qdrant_store
    )
    assert result.chunks >= 1

    query_vec = (await embedder.embed(["The capital of France is Paris."]))[0]
    hits = await qdrant_store.search(result.collection, query_vec, workspace_id, k=4)
    assert hits
    assert any("Paris" in h.get("text", "") for h in hits)

    # A different workspace must not see this document's chunks (tenant isolation).
    other = await qdrant_store.search(result.collection, query_vec, str(uuid4()), k=4)
    assert other == []


async def test_xlsx_ingest_is_retrievable(qdrant_store) -> None:
    dim = 8
    embedder = DeterministicMockEmbedder(dim)
    workspace_id = str(uuid4())
    job = DocumentJob(
        document_id=str(uuid4()),
        workspace_id=workspace_id,
        filename="sla.xlsx",
        embedding_dim=dim,
    )
    result = await process_document(
        data=_make_xlsx(),
        job=job,
        embedder=embedder,
        vector_store=qdrant_store,
    )
    query = "Critical incidents have a 4 hours resolution target"
    query_vec = (await embedder.embed([query]))[0]
    hits = await qdrant_store.search(result.collection, query_vec, workspace_id, k=4)
    assert any("Critical" in hit.get("text", "") for hit in hits)
    assert any("4 hours" in hit.get("text", "") for hit in hits)


async def test_parser_timeout_fails_before_indexing(qdrant_store, monkeypatch) -> None:
    # Parsing runs in a child process, so the stand-in must be importable.
    monkeypatch.setattr(pipeline_module, "extract_text", parse_helpers.slow_parse)
    job = DocumentJob(
        document_id=str(uuid4()),
        workspace_id=str(uuid4()),
        filename="slow.txt",
        embedding_dim=8,
    )
    with pytest.raises(TimeoutError, match="document parsing exceeded"):
        await process_document(
            data=b"ignored",
            job=job,
            embedder=DeterministicMockEmbedder(8),
            vector_store=qdrant_store,
            parse_timeout_seconds=0.005,
        )


async def test_markdown_ingestion_persists_outline_and_section_metadata() -> None:
    store = _CapturingVectorStore()
    job = DocumentJob(
        document_id=str(uuid4()),
        workspace_id=str(uuid4()),
        filename="gateway.md",
        embedding_dim=8,
    )
    data = b"""# Gateway
## Routes
Route details.
## Authentication
Authentication details.
## Rate Limiting
Rate-limit details.
"""

    result = await process_document(
        data=data,
        job=job,
        embedder=DeterministicMockEmbedder(8),
        vector_store=store,  # type: ignore[arg-type]
    )

    assert result.chunks == len(store.points)
    assert store.points[0].payload["chunk_kind"] == "outline"
    assert store.points[0].payload["chunk_index"] == 0
    assert store.points[0].payload["section_path"] == "# Gateway"
    assert "- Routes" in store.points[0].payload["text"]
    assert "- Authentication" in store.points[0].payload["text"]
    assert "- Rate Limiting" in store.points[0].payload["text"]
    assert all(point.payload["chunk_kind"] == "content" for point in store.points[1:])
    assert any(
        point.payload["section_path"] == "# Gateway\n## Authentication"
        for point in store.points[1:]
    )


async def test_50_page_pdf_local_pipeline_under_10s(qdrant_store) -> None:
    """Ingestion design target: a 50-page PDF parsed, chunked and upserted
    within 10 s. The mock embedder means this measures the local pipeline only;
    real embedding time depends on the configured embeddings gateway.
    """
    dim = 8
    embedder = DeterministicMockEmbedder(dim)
    pages = [
        f"Page {i}. " + ("lorem ipsum dolor sit amet consectetur adipiscing elit " * 12)
        for i in range(50)
    ]
    data = _make_pdf(pages)
    job = DocumentJob(
        document_id=str(uuid4()),
        workspace_id=str(uuid4()),
        filename="big.pdf",
        embedding_dim=dim,
    )

    start = time.perf_counter()
    result = await process_document(
        data=data, job=job, embedder=embedder, vector_store=qdrant_store
    )
    elapsed = time.perf_counter() - start

    assert result.chunks > 0
    assert elapsed < 10.0, f"50-page PDF local-pipeline budget exceeded: {elapsed:.2f}s"


async def test_reingest_shorter_document_removes_trailing_chunks(qdrant_store) -> None:
    from qdrant_client import models

    dim = 8
    embedder = DeterministicMockEmbedder(dim)
    workspace_id = str(uuid4())
    document_id = str(uuid4())
    job = DocumentJob(
        document_id=document_id,
        workspace_id=workspace_id,
        filename="versioned.txt",
        embedding_dim=dim,
    )

    first = await process_document(
        data=("old content " * 3000).encode(),
        job=job,
        embedder=embedder,
        vector_store=qdrant_store,
    )
    assert first.chunks > 1

    second = await process_document(
        data=b"new short content",
        job=job,
        embedder=embedder,
        vector_store=qdrant_store,
    )
    assert second.chunks == 1

    count = await qdrant_store.client.count(
        collection_name=second.collection,
        count_filter=models.Filter(
            must=[
                models.FieldCondition(
                    key="document_id",
                    match=models.MatchValue(value=document_id),
                )
            ]
        ),
        exact=True,
    )
    assert count.count == second.chunks
