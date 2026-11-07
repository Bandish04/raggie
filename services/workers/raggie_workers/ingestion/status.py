# SPDX-License-Identifier: Apache-2.0

"""Document status writer (ingestion workers own documents.status)."""

from __future__ import annotations

import json
import logging

import asyncpg

log = logging.getLogger("ingestion.status")

# A document is "live" (allowed to have chunks in Qdrant / have its status moved)
# only while it is neither soft-deleted nor archived: every query below carries
# `deleted_at IS NULL AND archived_at IS NULL` as a literal. Both lifecycle
# transitions are followed by a document.deleted cascade that drops the chunks;
# ingestion must never write them back.


class DocumentStatusStore:
    def __init__(self, db: asyncpg.Pool | asyncpg.Connection) -> None:
        self.db = db
        self._warned: set[str] = set()

    async def is_live(self, document_id: str) -> bool:
        """False when the row is missing, soft-deleted or archived."""
        row = await self.db.fetchval(
            "SELECT 1 FROM documents WHERE id = $1::uuid"
            " AND deleted_at IS NULL AND archived_at IS NULL",
            document_id,
        )
        return row is not None

    async def touch(self, document_id: str) -> None:
        """Heartbeat: the set_updated_at trigger bumps updated_at, which keeps
        the stale-PENDING sweep from re-publishing a document still in work."""
        await self.db.execute(
            "UPDATE documents SET status = status WHERE id = $1::uuid"
            " AND status = 'PROCESSING' AND deleted_at IS NULL AND archived_at IS NULL",
            document_id,
        )

    async def _execute(self, *attempts: tuple[str, tuple]) -> None:
        """Run the first statement the schema supports. Later attempts drop newer
        columns, for a DB whose control-plane migrations (0026 fingerprint, 0029
        error codes) are not applied yet in a rolling deploy. Only a missing
        column (SQLSTATE 42703) falls back; any other error propagates."""
        for sql, args in attempts[:-1]:
            try:
                await self.db.execute(sql, *args)
                return
            except asyncpg.UndefinedColumnError as exc:
                reason = str(exc)
                if reason not in self._warned:  # once per missing column, not per write
                    self._warned.add(reason)
                    log.warning(
                        "documents schema behind (pending migration): %s;"
                        " using an older status update",
                        reason,
                    )
        sql, args = attempts[-1]
        await self.db.execute(sql, *args)

    async def mark_processing(self, document_id: str) -> None:
        await self._clear(document_id, "PROCESSING")

    async def mark_success(self, document_id: str, fingerprint: str | None = None) -> None:
        if fingerprint is None:
            await self._clear(document_id, "SUCCESS")
            return
        await self._execute(
            (
                "UPDATE documents SET status = 'SUCCESS', error_message = NULL,"
                " error_code = NULL, error_params = NULL, embedding_fingerprint = $2"
                " WHERE id = $1::uuid AND deleted_at IS NULL AND archived_at IS NULL",
                (document_id, fingerprint),
            ),
            (
                "UPDATE documents SET status = 'SUCCESS', error_message = NULL,"
                " embedding_fingerprint = $2"
                " WHERE id = $1::uuid AND deleted_at IS NULL AND archived_at IS NULL",
                (document_id, fingerprint),
            ),
            (
                "UPDATE documents SET status = 'SUCCESS', error_message = NULL"
                " WHERE id = $1::uuid AND deleted_at IS NULL AND archived_at IS NULL",
                (document_id,),
            ),
        )

    async def mark_failed(
        self,
        document_id: str,
        error: str,
        *,
        terminal: bool = False,
        code: str | None = None,
        params: dict | None = None,
    ) -> None:
        """FAILED with the English reason plus its stable code/params
        (contracts/document_errors.md). ``terminal`` exhausts the retry budget so
        the auto-retry sweep leaves the doc alone (e.g. embedding-profile
        mismatch: only a re-embed can fix it)."""
        error = error[:2000]
        params_json = json.dumps(params) if params is not None else None
        if terminal:
            await self._execute(
                (
                    "UPDATE documents SET status = 'FAILED', error_message = $2,"
                    " error_code = $3, error_params = $4::jsonb,"
                    " retry_count = GREATEST(retry_count, max_retries)"
                    " WHERE id = $1::uuid AND deleted_at IS NULL AND archived_at IS NULL",
                    (document_id, error, code, params_json),
                ),
                (
                    "UPDATE documents SET status = 'FAILED', error_message = $2,"
                    " retry_count = GREATEST(retry_count, max_retries)"
                    " WHERE id = $1::uuid AND deleted_at IS NULL AND archived_at IS NULL",
                    (document_id, error),
                ),
            )
            return
        await self._execute(
            (
                "UPDATE documents SET status = 'FAILED', error_message = $2,"
                " error_code = $3, error_params = $4::jsonb"
                " WHERE id = $1::uuid AND deleted_at IS NULL AND archived_at IS NULL",
                (document_id, error, code, params_json),
            ),
            (
                "UPDATE documents SET status = 'FAILED', error_message = $2"
                " WHERE id = $1::uuid AND deleted_at IS NULL AND archived_at IS NULL",
                (document_id, error),
            ),
        )

    async def _clear(self, document_id: str, status: str) -> None:
        # Never resurrect a deleted/archived row's status (e.g. ARCHIVED -> SUCCESS,
        # or a deleted doc -> FAILED that the retry sweep would then re-enqueue).
        await self._execute(
            (
                "UPDATE documents SET status = $2, error_message = NULL,"
                " error_code = NULL, error_params = NULL"
                " WHERE id = $1::uuid AND deleted_at IS NULL AND archived_at IS NULL",
                (document_id, status),
            ),
            (
                "UPDATE documents SET status = $2, error_message = NULL"
                " WHERE id = $1::uuid AND deleted_at IS NULL AND archived_at IS NULL",
                (document_id, status),
            ),
        )
