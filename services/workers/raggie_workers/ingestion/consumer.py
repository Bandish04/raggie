# SPDX-License-Identifier: Apache-2.0

"""Ingestion consumer: document.uploaded -> process -> status + result event.

Consumes from the bus, fetches the raw file from the object store, runs the
ingestion pipeline, writes the terminal document status, and emits
document.processed / document.failed. A failure marks the document FAILED and
acks (no infinite redelivery); richer retry/DLQ is layered in later.
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from dataclasses import dataclass, field

import httpx
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse

from raggie_workers.bus import RedisStreamsBus
from raggie_workers.ingestion.embedder import Embedder, SparseEmbedder
from raggie_workers.ingestion.isolation import ParserCrashedError, ParseTimeoutError
from raggie_workers.ingestion.objectstore import ObjectStore
from raggie_workers.ingestion.openai_embedder import FingerprintMismatch
from raggie_workers.ingestion.parsing import (
    DocumentLimitError,
    InvalidDocumentError,
    ParserLimits,
    UnsupportedFormatError,
    safe_extension,
)
from raggie_workers.ingestion.pipeline import (
    DocumentGoneError,
    DocumentJob,
    IngestResult,
    process_document,
)
from raggie_workers.ingestion.status import DocumentStatusStore
from raggie_workers.ingestion.vectorstore import QdrantVectorStore
from raggie_workers.topics import (
    DOCUMENT_FAILED,
    DOCUMENT_PROCESSED,
    DOCUMENT_UPLOADED,
    INGESTION_GROUP,
)

log = logging.getLogger("ingestion")

# Max documents a single worker processes CONCURRENTLY. Bounds load on the
# embeddings service + Qdrant: with M ingestion-worker replicas the total in-flight
# is M * INGEST_MAX_CONCURRENCY — keep it near the embeddings capacity (~cores) so
# concurrent requests are QUEUED, not dropped ("Server disconnected" under flood).
_MAX_CONCURRENCY = max(1, int(os.environ.get("INGEST_MAX_CONCURRENCY", "4")))


_MAX_REASON_CHARS = 500


class ObjectReadError(RuntimeError):
    """The raw upload could not be fetched from the object store."""

    def __init__(self) -> None:
        super().__init__("The uploaded file could not be read from object storage")


def _sentence(text: str) -> str:
    text = " ".join(text.split())[: _MAX_REASON_CHARS - 1]
    if not text:
        return "Ingestion failed."
    text = text[0].upper() + text[1:]
    return text if text.endswith((".", "!", "?")) else f"{text}."


# Stable failure codes stored in documents.error_code (contracts/document_errors.md).
# The web renders them per language from code + error_params; error_message keeps
# an English sentence for the API and older clients.
FAILURE_CODES = (
    "parse_limit",
    "parse_invalid",
    "unsupported_format",
    "parse_timeout",
    "parser_crashed",
    "fingerprint_mismatch",
    "embeddings_http",
    "embeddings_unreachable",
    "vector_store",
    "object_read",
    "unexpected",
)


@dataclass(frozen=True)
class FailureReason:
    code: str
    params: dict
    message: str


def describe_failure(exc: BaseException) -> FailureReason:
    """Why a document failed: a stable code, its params and an English sentence.
    Parser and profile errors keep their own wording; everything else is
    summarised without URLs, hosts or raw exception text (the worker log has
    the full detail)."""
    if isinstance(exc, DocumentLimitError):
        params = {"kind": exc.kind}
        if exc.limit is not None:
            params["limit"] = exc.limit
        return FailureReason("parse_limit", params, _sentence(str(exc)))
    if isinstance(exc, InvalidDocumentError):
        return FailureReason("parse_invalid", {}, _sentence(str(exc)))
    if isinstance(exc, UnsupportedFormatError):
        params = {"extension": safe_extension(exc.extension)} if exc.extension else {}
        return FailureReason("unsupported_format", params, _sentence(str(exc)))
    if isinstance(exc, ParseTimeoutError):
        return FailureReason("parse_timeout", {"seconds": exc.seconds}, _sentence(str(exc)))
    if isinstance(exc, ParserCrashedError):
        return FailureReason("parser_crashed", {"exit_code": exc.exit_code}, _sentence(str(exc)))
    if isinstance(exc, FingerprintMismatch):
        return FailureReason(
            "fingerprint_mismatch",
            {"expected": exc.expected, "actual": exc.actual},
            _sentence(str(exc)),
        )
    if isinstance(exc, ObjectReadError):
        return FailureReason("object_read", {}, _sentence(str(exc)))
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return FailureReason(
            "embeddings_http",
            {"status": code},
            f"The embeddings service answered HTTP {code}; embedding failed.",
        )
    if isinstance(exc, httpx.TransportError):
        return FailureReason(
            "embeddings_unreachable",
            {},
            "The embeddings service could not be reached; embedding failed.",
        )
    if isinstance(exc, UnexpectedResponse | ResponseHandlingException):
        return FailureReason(
            "vector_store", {}, "The vector database did not accept the chunks; indexing failed."
        )
    return FailureReason(
        "unexpected",
        {},
        f"Ingestion failed unexpectedly ({type(exc).__name__}); "
        "details are in the ingestion worker logs.",
    )


@dataclass
class IngestionConsumer:
    bus: RedisStreamsBus
    object_store: ObjectStore
    embedder: Embedder
    vector_store: QdrantVectorStore
    status: DocumentStatusStore
    sparse_embedder: SparseEmbedder | None = None
    parser_limits: ParserLimits = field(default_factory=ParserLimits)
    parse_timeout_seconds: float = 120.0
    # updated_at heartbeat while a document is in work (see the stale-PENDING sweep).
    heartbeat_seconds: float = 60.0
    # Chunks per embeddings-gateway request (EMBED_BATCH_SIZE).
    embed_batch_size: int = 64

    async def _fail(self, document_id: str, exc: BaseException, *, terminal: bool = False) -> None:
        reason = describe_failure(exc)
        await self.status.mark_failed(
            document_id, reason.message, terminal=terminal, code=reason.code, params=reason.params
        )
        await self.bus.publish(
            DOCUMENT_FAILED,
            {"document_id": document_id, "error": reason.message, "error_code": reason.code},
        )

    async def _heartbeat(self, document_id: str) -> None:
        while True:
            await asyncio.sleep(self.heartbeat_seconds)
            try:
                await self.status.touch(document_id)
            except Exception:  # noqa: BLE001 — a missed beat must not fail ingestion
                log.warning("heartbeat failed for document %s", document_id, exc_info=True)

    async def handle(self, payload: dict) -> IngestResult | None:
        document_id = payload["document_id"]
        # A deleted/archived document must not be (re-)indexed: its chunks were or
        # will be purged by the document.deleted cascade. Ack and drop the event.
        if not await self.status.is_live(document_id):
            log.info("skipping ingestion of removed document %s", document_id)
            return None
        await self.status.mark_processing(document_id)
        # Stream the raw object to a temp file so multi-GB documents are parsed
        # from disk, never loaded whole into the worker's memory.
        suffix = os.path.splitext(payload.get("filename", ""))[1]
        fd, tmp_path = tempfile.mkstemp(suffix=suffix, prefix="raggie-ingest-")
        os.close(fd)
        heartbeat = asyncio.create_task(self._heartbeat(document_id))
        try:
            try:
                await self.object_store.download_to_file(payload["object_key"], tmp_path)
            except Exception as exc:  # noqa: BLE001 — any store error means "unreadable"
                raise ObjectReadError() from exc
            job = DocumentJob(
                document_id=document_id,
                workspace_id=payload["workspace_id"],
                filename=payload["filename"],
                embedding_dim=int(payload["embedding_dim"]),
                # Additive event fields (control-plane, embedding gateway profile).
                collection=payload.get("collection") or None,
                embedding_fingerprint=payload.get("embedding_fingerprint") or None,
            )
            result = await process_document(
                source_path=tmp_path,
                job=job,
                embedder=self.embedder,
                vector_store=self.vector_store,
                sparse_embedder=self.sparse_embedder,
                batch_size=self.embed_batch_size,
                parser_limits=self.parser_limits,
                parse_timeout_seconds=self.parse_timeout_seconds,
                is_live=lambda: self.status.is_live(document_id),
            )
            await self.status.mark_success(document_id, result.fingerprint)
            await self.bus.publish(
                DOCUMENT_PROCESSED,
                {
                    "document_id": document_id,
                    "chunks": result.chunks,
                    "collection": result.collection,
                },
            )
            return result
        except FingerprintMismatch as exc:
            # Terminal: the gateway now embeds with another profile; retrying
            # cannot help until the document is re-embedded under the new one.
            log.error("embedding profile mismatch for document %s: %s", document_id, exc)
            await self._fail(document_id, exc, terminal=True)
            return None
        except DocumentGoneError:
            # Not a failure: the user removed the document mid-ingestion. The
            # pipeline already purged any points it wrote; leave the row alone.
            log.info("document %s was removed during ingestion; dropped", document_id)
            return None
        except Exception as exc:  # noqa: BLE001 — failure is recorded, not swallowed silently
            log.exception("ingestion failed for document %s", document_id)
            await self._fail(document_id, exc)
            return None
        finally:
            heartbeat.cancel()
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    async def run_once(self, consumer_name: str = "ingestion-1") -> int:
        await self.bus.ensure_group(DOCUMENT_UPLOADED, INGESTION_GROUP)
        msgs = await self.bus.consume(DOCUMENT_UPLOADED, INGESTION_GROUP, consumer_name)
        if not msgs:
            return 0
        # Process the fetched batch concurrently but BOUNDED — a semaphore caps how
        # many docs embed/upsert at once so a big backlog can't flood the embeddings
        # service. handle() records FAILED internally and never re-raises, so one
        # failure can't abort its siblings; we still guard with return_exceptions
        # and ack only the messages that didn't raise (a raised one stays pending
        # for redelivery rather than being lost).
        sem = asyncio.Semaphore(_MAX_CONCURRENCY)

        async def _bounded(payload: dict) -> IngestResult | None:
            async with sem:
                return await self.handle(payload)

        results = await asyncio.gather(
            *(_bounded(payload) for _msg_id, payload in msgs),
            return_exceptions=True,
        )
        for (msg_id, _payload), res in zip(msgs, results, strict=True):
            if not isinstance(res, BaseException):
                await self.bus.ack(DOCUMENT_UPLOADED, INGESTION_GROUP, msg_id)
        return len(msgs)
