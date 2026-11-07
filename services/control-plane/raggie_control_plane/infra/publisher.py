# SPDX-License-Identifier: Apache-2.0

"""Event publisher (producer side) over Redis Streams.

Publishes against the same wire envelope the workers consume (a single ``data``
field holding the JSON payload). The event contract is documented in
contracts/events.md.
"""

from __future__ import annotations

import json
from typing import Protocol, runtime_checkable

import redis.asyncio as aioredis


@runtime_checkable
class EventPublisher(Protocol):
    async def publish(self, topic: str, payload: dict) -> str: ...


class RedisEventPublisher:
    def __init__(self, redis: aioredis.Redis) -> None:
        self._redis = redis

    async def publish(self, topic: str, payload: dict) -> str:
        return await self._redis.xadd(topic, {"data": json.dumps(payload)})


# Topic names (must match the workers' raggie_workers/topics.py and contracts/events.md).
DOCUMENT_UPLOADED = "raggie.document.uploaded"
DOCUMENT_DELETED = "raggie.document.deleted"
