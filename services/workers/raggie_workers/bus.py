# SPDX-License-Identifier: Apache-2.0

"""Event bus on Redis/Valkey Streams.

At-least-once delivery via consumer groups and explicit acks; messages left
pending by a crashed consumer are reclaimed after an idle timeout.
"""

from __future__ import annotations

import json

import redis.asyncio as aioredis

DEFAULT_CLAIM_IDLE_MS = 5 * 60 * 1000


class RedisStreamsBus:
    def __init__(self, redis: aioredis.Redis) -> None:
        self._redis = redis

    async def publish(self, stream: str, payload: dict) -> str:
        return await self._redis.xadd(stream, {"data": json.dumps(payload)})

    async def ensure_group(self, stream: str, group: str) -> None:
        try:
            await self._redis.xgroup_create(stream, group, id="0", mkstream=True)
        except aioredis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise  # group already exists is fine; anything else is real

    async def consume(
        self,
        stream: str,
        group: str,
        consumer: str,
        *,
        count: int = 10,
        block_ms: int = 1000,
        claim_idle_ms: int = DEFAULT_CLAIM_IDLE_MS,
    ) -> list[tuple[str, dict]]:
        # XREADGROUP with ">" cannot see messages left pending by a crashed
        # consumer. Reclaim stale work before reading new entries.
        claimed = await self._redis.xautoclaim(
            stream,
            group,
            consumer,
            min_idle_time=claim_idle_ms,
            start_id="0-0",
            count=count,
        )
        claimed_messages = claimed[1] if len(claimed) > 1 else []
        if claimed_messages:
            return self._decode_messages(claimed_messages)

        resp = await self._redis.xreadgroup(
            group, consumer, {stream: ">"}, count=count, block=block_ms
        )
        out: list[tuple[str, dict]] = []
        for _stream, messages in resp or []:
            out.extend(self._decode_messages(messages))
        return out

    async def delivery_count(self, stream: str, group: str, msg_id: str) -> int:
        """How many times a pending message has been delivered (XREADGROUP and
        each XAUTOCLAIM count); 0 when it is no longer pending."""
        pending = await self._redis.xpending_range(stream, group, msg_id, msg_id, 1)
        return int(pending[0]["times_delivered"]) if pending else 0

    async def ack(self, stream: str, group: str, msg_id: str) -> None:
        await self._redis.xack(stream, group, msg_id)

    @staticmethod
    def _decode_messages(messages: list) -> list[tuple[str, dict]]:
        return [(msg_id, json.loads(fields["data"])) for msg_id, fields in messages]
