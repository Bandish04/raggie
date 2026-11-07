# SPDX-License-Identifier: Apache-2.0

"""Redis query-embedding cache.

Key ``emb:q:{fingerprint}:{sha256(normalized query)}``, value the dense vector
as raw float32 bytes, TTL 24h by default. The fingerprint in the key means a
profile change can never serve a vector from another model. Every Redis error
is a miss: the cache only ever makes queries faster, never fails them. Each
call is hard-bounded (redis-py retries and DNS included) and after a failure the
cache is skipped for a cooldown, so a dead Redis costs one short timeout per
cooldown window instead of one per query.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
import unicodedata
from collections.abc import Callable
from typing import Any

import numpy as np

from raggie_embeddings.providers.metrics import QUERY_CACHE

logger = logging.getLogger("raggie.embeddings.cache")
_WS = re.compile(r"\s+")


def normalize_query(text: str) -> str:
    # Case is preserved on purpose: dense models are case-sensitive and Turkish
    # casing (I/ı, İ/i) does not survive naive lowercasing.
    return _WS.sub(" ", unicodedata.normalize("NFKC", text)).strip()


class QueryCache:
    def __init__(
        self,
        redis: Any,
        *,
        fingerprint: str,
        ttl_seconds: int,
        timeout_seconds: float = 0.5,
        cooldown_seconds: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._redis = redis
        self._fingerprint = fingerprint
        self._ttl = ttl_seconds
        self._timeout = timeout_seconds
        self._cooldown = cooldown_seconds
        self._clock = clock
        self._skip_until = 0.0

    def key(self, query: str) -> str:
        digest = hashlib.sha256(normalize_query(query).encode("utf-8")).hexdigest()
        return f"emb:q:{self._fingerprint}:{digest}"

    def _available(self) -> bool:
        return self._clock() >= self._skip_until

    def _failed(self, operation: str, exc: BaseException) -> None:
        QUERY_CACHE.labels("error").inc()
        self._skip_until = self._clock() + self._cooldown
        # Type only: redis-py error text can embed connection details.
        logger.warning(
            "query cache %s failed (%s); bypassing the cache for %.0fs",
            operation,
            type(exc).__name__,
            self._cooldown,
        )

    async def get(self, query: str) -> list[float] | None:
        if not self._available():
            QUERY_CACHE.labels("miss").inc()
            return None
        try:
            raw = await asyncio.wait_for(self._redis.get(self.key(query)), self._timeout)
        except Exception as exc:  # noqa: BLE001 — cache is best-effort (incl. TimeoutError)
            self._failed("read", exc)
            return None
        if not raw or len(raw) % 4:
            QUERY_CACHE.labels("miss").inc()
            return None
        QUERY_CACHE.labels("hit").inc()
        return np.frombuffer(raw, dtype=np.float32).astype(float).tolist()

    async def set(self, query: str, vector: list[float]) -> None:
        if not self._available():
            return
        try:
            await asyncio.wait_for(
                self._redis.set(
                    self.key(query), np.asarray(vector, dtype=np.float32).tobytes(), ex=self._ttl
                ),
                self._timeout,
            )
        except Exception as exc:  # noqa: BLE001 — cache is best-effort
            self._failed("write", exc)
