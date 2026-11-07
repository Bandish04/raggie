# SPDX-License-Identifier: Apache-2.0

"""Audit log and usage analytics."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

import asyncpg


class AuditRepo:
    """Append-only audit trail. Best-effort: a failed audit
    write must never block the action it records."""

    def __init__(self, conn: asyncpg.Connection) -> None:
        self.conn = conn

    async def record(
        self,
        action: str,
        *,
        org_id: UUID | None = None,
        actor_user_id: UUID | None = None,
        target: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        await self.conn.execute(
            "INSERT INTO audit_log (org_id, actor_user_id, action, target, metadata)"
            " VALUES ($1, $2, $3, $4, $5)",
            org_id,
            actor_user_id,
            action,
            target,
            metadata,  # the pool's jsonb codec serializes; json.dumps would double-encode
        )

    async def last_recorded_at(self, action: str) -> datetime | None:
        return await self.conn.fetchval(
            "SELECT max(created_at) FROM audit_log WHERE action = $1", action
        )

    async def list(self, *, org_id: UUID | None = None, limit: int = 100) -> list[dict]:
        if org_id is not None:
            rows = await self.conn.fetch(
                "SELECT action, target, metadata, actor_user_id::text AS actor, created_at"
                " FROM audit_log WHERE org_id = $1 ORDER BY created_at DESC LIMIT $2",
                org_id,
                limit,
            )
        else:
            rows = await self.conn.fetch(
                "SELECT action, target, metadata, actor_user_id::text AS actor, created_at"
                " FROM audit_log ORDER BY created_at DESC LIMIT $1",
                limit,
            )
        return [dict(r) for r in rows]


class AnalyticsRepo:
    """Read-only aggregate metrics for the admin dashboard, scoped to a set of
    workspace ids (empty set -> all-zero, never errors)."""

    def __init__(self, conn: asyncpg.Connection) -> None:
        self.conn = conn

    async def summary(self, workspace_ids: list[UUID]) -> dict:
        docs = await self.conn.fetch(
            "SELECT status, count(*) AS n FROM documents"
            " WHERE workspace_id = ANY($1::uuid[]) AND deleted_at IS NULL"
            " GROUP BY status",
            workspace_ids,
        )
        by_status = {r["status"]: r["n"] for r in docs}
        conv = await self.conn.fetchrow(
            "SELECT count(*) AS total, count(*) FILTER (WHERE is_flagged) AS flagged"
            " FROM conversations WHERE workspace_id = ANY($1::uuid[])",
            workspace_ids,
        )
        msg = await self.conn.fetchrow(
            "SELECT count(*) AS total, COALESCE(sum(used_tokens), 0) AS tokens"
            " FROM messages m JOIN conversations c ON m.conversation_id = c.id"
            " WHERE c.workspace_id = ANY($1::uuid[])",
            workspace_ids,
        )
        activity = await self.conn.fetch(
            "SELECT to_char(d::date, 'YYYY-MM-DD') AS date, COALESCE(x.cnt, 0) AS messages"
            " FROM generate_series(current_date - 6, current_date, interval '1 day') d"
            " LEFT JOIN ("
            "   SELECT date_trunc('day', m.created_at)::date AS dd, count(*) AS cnt"
            "   FROM messages m JOIN conversations c ON m.conversation_id = c.id"
            "   WHERE c.workspace_id = ANY($1::uuid[])"
            "     AND m.created_at >= current_date - 6"
            "   GROUP BY dd"
            " ) x ON x.dd = d::date"
            " ORDER BY d",
            workspace_ids,
        )
        return {
            "documents": {
                "total": sum(by_status.values()),
                "pending": by_status.get("PENDING", 0),
                "processing": by_status.get("PROCESSING", 0),
                "success": by_status.get("SUCCESS", 0),
                "failed": by_status.get("FAILED", 0),
            },
            "conversations": conv["total"] if conv else 0,
            "flagged": conv["flagged"] if conv else 0,
            "messages": msg["total"] if msg else 0,
            "tokens_used": msg["tokens"] if msg else 0,
            "activity": [{"date": r["date"], "messages": r["messages"]} for r in activity],
        }

    async def usage_by_user(self, workspace_ids: list[UUID]) -> list[dict]:
        """Per-user message volume + token spend across the given workspaces,
        highest spenders first. Anonymous EXTERNAL widget traffic (conversations
        with a NULL user_id) is aggregated into a single synthetic row so it is
        surfaced rather than silently dropped; that row has user_id=None and a
        sentinel email/full_name of 'anonymous'."""
        rows = await self.conn.fetch(
            "SELECT c.user_id::text AS user_id, u.email, u.full_name,"
            "       count(m.id) AS message_count,"
            "       COALESCE(sum(m.used_tokens), 0) AS total_tokens"
            " FROM messages m"
            " JOIN conversations c ON m.conversation_id = c.id"
            " LEFT JOIN users u ON u.id = c.user_id"
            " WHERE c.workspace_id = ANY($1::uuid[])"
            " GROUP BY c.user_id, u.email, u.full_name"
            " ORDER BY total_tokens DESC, message_count DESC",
            workspace_ids,
        )
        out: list[dict] = []
        for r in rows:
            anon = r["user_id"] is None
            out.append(
                {
                    "user_id": r["user_id"],
                    "email": r["email"] or ("anonymous" if anon else ""),
                    "full_name": r["full_name"] or ("anonymous" if anon else None),
                    "message_count": r["message_count"],
                    "total_tokens": r["total_tokens"],
                }
            )
        return out

    async def list_flagged(self, workspace_ids: list[UUID], *, limit: int = 100) -> list[dict]:
        """Flagged conversations with the worst message's explainable metrics."""
        rows = await self.conn.fetch(
            "SELECT c.id::text AS id, c.workspace_id::text AS workspace_id,"
            "       c.evaluation_score, c.created_at, e.faithfulness_score,"
            "       e.citation_validity_score, e.citation_coverage_score,"
            "       (SELECT content FROM messages m WHERE m.conversation_id = c.id"
            "          AND m.sender = 'USER' ORDER BY m.created_at LIMIT 1) AS preview"
            " FROM conversations c"
            " LEFT JOIN LATERAL ("
            "   SELECT faithfulness_score, citation_validity_score, citation_coverage_score"
            "   FROM messages m WHERE m.conversation_id = c.id"
            "     AND m.evaluation_flagged = TRUE"
            "   ORDER BY m.evaluation_score ASC NULLS LAST, m.created_at DESC LIMIT 1"
            " ) e ON TRUE"
            " WHERE c.workspace_id = ANY($1::uuid[]) AND c.is_flagged"
            " ORDER BY c.created_at DESC LIMIT $2",
            workspace_ids,
            limit,
        )
        return [
            {
                "id": r["id"],
                "workspace_id": r["workspace_id"],
                "evaluation_score": r["evaluation_score"],
                "faithfulness_score": r["faithfulness_score"],
                "citation_validity_score": r["citation_validity_score"],
                "citation_coverage_score": r["citation_coverage_score"],
                "preview": r["preview"],
                "created_at": r["created_at"].isoformat(),
            }
            for r in rows
        ]
