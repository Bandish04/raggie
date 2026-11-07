# SPDX-License-Identifier: Apache-2.0

import os
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest_asyncio
import redis.asyncio as aioredis

from raggie_workers.bus import RedisStreamsBus

REDIS_URL = os.environ.get("REDIS_TEST_URL", "redis://localhost:56379")


@pytest_asyncio.fixture
async def bus() -> AsyncIterator[RedisStreamsBus]:
    redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    try:
        yield RedisStreamsBus(redis)
    finally:
        await redis.aclose()


async def test_publish_consume_ack(bus) -> None:
    stream = f"test.stream.{uuid4()}"
    group = "g1"
    await bus.ensure_group(stream, group)
    await bus.publish(stream, {"document_id": "abc", "n": 1})

    msgs = await bus.consume(stream, group, "c1", count=10, block_ms=500)
    assert len(msgs) == 1
    msg_id, payload = msgs[0]
    assert payload == {"document_id": "abc", "n": 1}

    await bus.ack(stream, group, msg_id)
    # Nothing new to read after ack.
    assert await bus.consume(stream, group, "c1", count=10, block_ms=200) == []


async def test_ensure_group_is_idempotent(bus) -> None:
    stream = f"test.stream.{uuid4()}"
    await bus.ensure_group(stream, "g")
    await bus.ensure_group(stream, "g")  # BUSYGROUP swallowed, no raise


async def test_consume_reclaims_pending_from_stale_consumer(bus) -> None:
    stream = f"test.stream.{uuid4()}"
    group = "g-reclaim"
    await bus.ensure_group(stream, group)
    await bus.publish(stream, {"document_id": "stuck"})

    first = await bus.consume(
        stream, group, "crashed-worker", count=1, block_ms=100, claim_idle_ms=0
    )
    assert len(first) == 1

    reclaimed = await bus.consume(
        stream, group, "replacement-worker", count=1, block_ms=100, claim_idle_ms=0
    )
    assert reclaimed == first
    await bus.ack(stream, group, reclaimed[0][0])


async def test_delivery_count_tracks_redeliveries(bus) -> None:
    stream = f"test.stream.{uuid4()}"
    group = "g1"
    await bus.ensure_group(stream, group)
    await bus.publish(stream, {"n": 1})
    [(msg_id, _payload)] = await bus.consume(stream, group, "c1", block_ms=500)
    assert await bus.delivery_count(stream, group, msg_id) == 1
    # Left unacked, it is reclaimed (claim_idle_ms=0) and counted again.
    assert [m for m, _ in await bus.consume(stream, group, "c2", claim_idle_ms=0)] == [msg_id]
    assert await bus.delivery_count(stream, group, msg_id) == 2
    await bus.ack(stream, group, msg_id)
    assert await bus.delivery_count(stream, group, msg_id) == 0
