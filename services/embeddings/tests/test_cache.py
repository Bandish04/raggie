# SPDX-License-Identifier: Apache-2.0

import hashlib

import fakeredis.aioredis
import numpy as np
import pytest

from raggie_embeddings.providers.cache import QueryCache, normalize_query


@pytest.fixture
async def redis():
    client = fakeredis.aioredis.FakeRedis()
    try:
        yield client
    finally:
        await client.aclose()


def test_normalization_collapses_whitespace_and_unicode_forms() -> None:
    assert normalize_query("  İzin   politikası\n nedir? ") == "İzin politikası nedir?"
    assert normalize_query("ﬁle") == normalize_query("file")  # NFKC
    assert normalize_query("Case") != normalize_query("case")  # case matters to the model


async def test_roundtrip_float32_with_fingerprinted_key(redis) -> None:
    cache = QueryCache(redis, fingerprint="abcd1234", ttl_seconds=60)
    vector = [0.25, -1.5, 3.0]

    assert await cache.get("what is the leave policy?") is None
    await cache.set("what is the leave policy?", vector)

    digest = hashlib.sha256(b"what is the leave policy?").hexdigest()
    key = f"emb:q:abcd1234:{digest}"
    raw = await redis.get(key)
    assert raw == np.asarray(vector, dtype=np.float32).tobytes()
    assert 0 < await redis.ttl(key) <= 60
    assert await cache.get("  what is the   leave policy? ") == vector


async def test_fingerprint_isolates_entries(redis) -> None:
    await QueryCache(redis, fingerprint="aaaa0000", ttl_seconds=60).set("q", [1.0])
    assert await QueryCache(redis, fingerprint="bbbb1111", ttl_seconds=60).get("q") is None


class _BrokenRedis:
    async def get(self, *_a, **_k):
        raise ConnectionError("redis down")

    async def set(self, *_a, **_k):
        raise ConnectionError("redis down")


async def test_redis_errors_fail_open() -> None:
    cache = QueryCache(_BrokenRedis(), fingerprint="abcd1234", ttl_seconds=60)
    assert await cache.get("q") is None
    await cache.set("q", [1.0])  # must not raise


async def test_corrupt_entry_is_a_miss(redis) -> None:
    cache = QueryCache(redis, fingerprint="abcd1234", ttl_seconds=60)
    await redis.set(cache.key("q"), b"\x00\x01\x02")  # not a multiple of 4 bytes
    assert await cache.get("q") is None


class _HangingRedis:
    def __init__(self) -> None:
        self.calls = 0

    async def get(self, *_a, **_k):
        self.calls += 1
        import asyncio

        await asyncio.sleep(30)

    async def set(self, *_a, **_k):
        self.calls += 1
        import asyncio

        await asyncio.sleep(30)


async def test_slow_redis_is_bounded_and_then_skipped() -> None:
    import time

    now = {"t": 100.0}
    redis = _HangingRedis()
    cache = QueryCache(
        redis,
        fingerprint="abcd1234",
        ttl_seconds=60,
        timeout_seconds=0.05,
        cooldown_seconds=30,
        clock=lambda: now["t"],
    )

    started = time.monotonic()
    assert await cache.get("q") is None
    assert time.monotonic() - started < 1.0  # hard bound, not redis-py's retries
    assert redis.calls == 1

    # While cooling down, Redis is not touched at all.
    assert await cache.get("q") is None
    await cache.set("q", [1.0])
    assert redis.calls == 1

    now["t"] += 31  # cooldown over: try again
    assert await cache.get("q") is None
    assert redis.calls == 2
