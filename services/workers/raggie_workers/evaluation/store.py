# SPDX-License-Identifier: Apache-2.0

"""DB access for per-message faithfulness/citation evaluation."""

from __future__ import annotations

import json

import asyncpg


class EvalStore:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def load_bot_message(self, message_id: str) -> dict | None:
        row = await self._pool.fetchrow(
            "SELECT content, sources_json, partial, conversation_id::text AS conversation_id"
            " FROM messages WHERE id = $1::uuid AND sender = 'BOT'",
            message_id,
        )
        if row is None:
            return None
        return {
            "content": row["content"],
            "context": context_from_sources(row["sources_json"]),
            "source_count": source_count(row["sources_json"]),
            "partial": row["partial"],
            "conversation_id": row["conversation_id"],
        }

    async def record(
        self,
        message_id: str,
        conversation_id: str,
        *,
        overall_score: float,
        faithfulness_score: float | None,
        citation_validity_score: float | None,
        citation_coverage_score: float | None,
        flagged: bool,
        details: dict,
    ) -> None:
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute(
                "UPDATE messages SET evaluation_score=$2, faithfulness_score=$3,"
                " citation_validity_score=$4, citation_coverage_score=$5,"
                " evaluation_flagged=$6, evaluation_json=$7::jsonb, evaluated_at=now()"
                " WHERE id=$1::uuid AND sender='BOT'",
                message_id,
                overall_score,
                faithfulness_score,
                citation_validity_score,
                citation_coverage_score,
                flagged,
                json.dumps(details),
            )
            await conn.execute(
                "UPDATE conversations c SET"
                " evaluation_score=COALESCE(("
                "   SELECT MIN(m.evaluation_score) FROM messages m"
                "   WHERE m.conversation_id=c.id AND m.evaluated_at IS NOT NULL"
                " ), 1.0),"
                " is_flagged=EXISTS("
                "   SELECT 1 FROM messages m WHERE m.conversation_id=c.id"
                "   AND m.evaluation_flagged=TRUE"
                " )"
                " WHERE c.id=$1::uuid",
                conversation_id,
            )


def context_from_sources(sources_json: object) -> str:
    """Flatten the cited chunks' text into the context the answer should be
    faithful to. Accepts the raw jsonb (str) or an already-decoded list."""
    data = _decode_sources(sources_json)
    if not isinstance(data, list):
        return ""
    parts = [str(item.get("text", "")) for item in data if isinstance(item, dict)]
    return "\n\n".join(p for p in parts if p)


def source_count(sources_json: object) -> int:
    data = _decode_sources(sources_json)
    return len(data) if isinstance(data, list) else 0


def _decode_sources(sources_json: object) -> object:
    if not sources_json:
        return []
    if isinstance(sources_json, str):
        try:
            return json.loads(sources_json)
        except json.JSONDecodeError:
            return []
    return sources_json
