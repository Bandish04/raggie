# SPDX-License-Identifier: Apache-2.0

"""Ingestion orchestration: parse -> chunk -> batched embed -> Qdrant upsert.

Design target: a 50-page text PDF in about 10 s from worker pickup (queue wait
excluded; docs/ARCHITECTURE.md, "Design targets"). Embeddings are sent in
batches to stay within it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

from raggie_workers.ingestion.chunking import chunk_document
from raggie_workers.ingestion.collection import collection_name
from raggie_workers.ingestion.embedder import Embedder, SparseEmbedder
from raggie_workers.ingestion.isolation import run_isolated
from raggie_workers.ingestion.openai_embedder import EmbedResult, FingerprintMismatch
from raggie_workers.ingestion.parsing import (
    ParserLimits,
    extract_text,
    extract_text_from_path,
)
from raggie_workers.ingestion.vectorstore import ChunkPoint, QdrantVectorStore


class DocumentGoneError(RuntimeError):
    """The document was deleted or archived while it was being ingested."""


@dataclass
class DocumentJob:
    document_id: str
    workspace_id: str
    filename: str
    embedding_dim: int
    # From the document.uploaded event (control-plane, gateway profile). When
    # set, `collection` wins over anything derived here and
    # `embedding_fingerprint` must match the gateway's active profile.
    collection: str | None = None
    embedding_fingerprint: str | None = None


@dataclass
class IngestResult:
    document_id: str
    collection: str
    chunks: int
    # The gateway profile the chunks were embedded with (None: legacy gateway).
    fingerprint: str | None = None


async def _embed_batch(
    embedder: Embedder, texts: list[str], expected_fingerprint: str | None
) -> EmbedResult:
    """Embed via the gateway-aware path when the embedder offers it."""
    with_profile = getattr(embedder, "embed_with_profile", None)
    if with_profile is not None:
        return await with_profile(texts, expected_fingerprint=expected_fingerprint)
    return EmbedResult(await embedder.embed(texts), None, None)


def _point_id(document_id: str, index: int) -> str:
    # Deterministic id => re-ingesting a document overwrites instead of duplicating.
    return str(uuid5(NAMESPACE_URL, f"{document_id}:{index}"))


async def process_document(
    *,
    job: DocumentJob,
    embedder: Embedder,
    vector_store: QdrantVectorStore,
    data: bytes | None = None,
    source_path: str | None = None,
    sparse_embedder: SparseEmbedder | None = None,
    batch_size: int = 64,
    parser_limits: ParserLimits | None = None,
    parse_timeout_seconds: float = 120.0,
    is_live: Callable[[], Awaitable[bool]] | None = None,
) -> IngestResult:
    # Prefer the on-disk path (large files stream from disk, never fully in RAM).
    # `data=` is kept for small in-memory callers and tests.
    if source_path is not None:
        parse, source = extract_text_from_path, source_path
    elif data is not None:
        parse, source = extract_text, data
    else:
        raise ValueError("process_document requires either data or source_path")
    # Office/PDF parsing is synchronous, CPU-heavy and fed untrusted input. It runs
    # in a disposable child process: the event loop stays live, and on timeout the
    # child is killed (a thread would keep running) — a hostile document can only
    # exhaust its own process, never the worker.
    text = await run_isolated(
        parse,
        job.filename,
        source,
        limits=parser_limits,
        timeout=parse_timeout_seconds,
    )
    chunks = chunk_document(text)

    # Every batch must come from one embedding profile: the job's when the event
    # carries one, else the first the gateway reports (a mid-document profile
    # switch would mix vector spaces in one document).
    fingerprint = job.embedding_fingerprint
    gateway_collection: str | None = None
    points: list[ChunkPoint] = []
    for start in range(0, len(chunks), batch_size):
        batch = chunks[start : start + batch_size]
        batch_texts = [chunk.text for chunk in batch]
        embedded = await _embed_batch(embedder, batch_texts, fingerprint)
        vectors = embedded.vectors
        if embedded.fingerprint:
            if fingerprint and embedded.fingerprint != fingerprint:
                raise FingerprintMismatch(fingerprint, embedded.fingerprint, mid_document=True)
            fingerprint = embedded.fingerprint
        gateway_collection = gateway_collection or embedded.collection
        # Hybrid: also compute BM25 sparse per chunk. None → dense-only points.
        sparse = await sparse_embedder.embed_sparse(batch_texts) if sparse_embedder else None
        for offset, (chunk, vector) in enumerate(zip(batch, vectors, strict=True)):
            index = start + offset
            sv = sparse[offset] if sparse else None
            points.append(
                ChunkPoint(
                    id=_point_id(job.document_id, index),
                    dense=vector,
                    sparse_indices=sv.indices if sv else None,
                    sparse_values=sv.values if sv else None,
                    payload={
                        "workspace_id": job.workspace_id,
                        "document_id": job.document_id,
                        "filename": job.filename,
                        "chunk_index": index,
                        "chunk_kind": chunk.kind,
                        "section_path": chunk.section_path,
                        "text": chunk.text,
                    },
                )
            )

    # Collection precedence: the event's (authoritative, control-plane) > the
    # gateway's (profile-aware) > the legacy dim-derived name.
    collection = job.collection or gateway_collection or collection_name(job.embedding_dim)
    await vector_store.ensure_collection(collection, job.embedding_dim)

    # Deletion race guard (KVKK erasure). The control-plane commits deleted_at /
    # archived_at BEFORE publishing document.deleted, so checking liveness after
    # our upsert closes the window: either we observe the deletion here and purge
    # our own points, or the cascade runs after this check and deletes them.
    if is_live is not None and not await is_live():
        raise DocumentGoneError(f"document {job.document_id} was removed before indexing")
    await vector_store.upsert(collection, points)
    await vector_store.delete_stale_document_chunks(collection, job.document_id, len(points))
    if is_live is not None and not await is_live():
        await vector_store.delete_by_document(collection, job.document_id)
        raise DocumentGoneError(f"document {job.document_id} was removed during indexing")
    return IngestResult(
        document_id=job.document_id,
        collection=collection,
        chunks=len(points),
        fingerprint=fingerprint,
    )
