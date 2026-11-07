# SPDX-License-Identifier: Apache-2.0

"""Idempotency guard keyed on message_id: a re-delivered
chat.completed is a no-op, so a message is never double-scored / double-flagged.
Uses Redis SET NX as an atomic claim (same pattern as the edge's idempotency)."""

from __future__ import annotations

from typing import Protocol
from uuid import uuid4

import redis.asyncio as aioredis


class Deduper(Protocol):
    async def claim(self, message_id: str) -> str | None:
        """Return an ownership token, or None when already claimed/completed."""
        ...

    async def complete(self, message_id: str, token: str) -> None:
        """Mark a successfully handled message as completed."""
        ...

    async def release(self, message_id: str, token: str) -> None:
        """Release a failed claim so Redis Streams may redeliver it."""
        ...


class RedisDeduper:
    def __init__(
        self, redis: aioredis.Redis, ttl_seconds: int = 86_400, prefix: str = "eval:done:"
    ) -> None:
        self._redis = redis
        self._ttl = ttl_seconds
        self._prefix = prefix

    async def claim(self, message_id: str) -> str | None:
        token = uuid4().hex
        created = await self._redis.set(
            self._prefix + message_id,
            token,
            nx=True,
            ex=min(self._ttl, 300),
        )
        return token if created else None

    async def complete(self, message_id: str, token: str) -> None:
        await self._redis.eval(
            "if redis.call('get', KEYS[1]) == ARGV[1] then "
            "return redis.call('set', KEYS[1], 'done', 'EX', ARGV[2]) else return 0 end",
            1,
            self._prefix + message_id,
            token,
            self._ttl,
        )

    async def release(self, message_id: str, token: str) -> None:
        await self._redis.eval(
            "if redis.call('get', KEYS[1]) == ARGV[1] then "
            "return redis.call('del', KEYS[1]) else return 0 end",
            1,
            self._prefix + message_id,
            token,
        )


class InMemoryDeduper:
    """Test/dev fallback with no Redis dependency."""

    def __init__(self) -> None:
        self._claims: dict[str, str] = {}

    async def claim(self, message_id: str) -> str | None:
        if message_id in self._claims:
            return None
        token = uuid4().hex
        self._claims[message_id] = token
        return token

    async def complete(self, message_id: str, token: str) -> None:
        # A claim token is an in-process ownership marker, not a secret.
        if self._claims.get(message_id) == token:  # nosemgrep: raggie-secret-compared-without-hmac
            self._claims[message_id] = "done"

    async def release(self, message_id: str, token: str) -> None:
        if self._claims.get(message_id) == token:  # nosemgrep: raggie-secret-compared-without-hmac
            self._claims.pop(message_id, None)
