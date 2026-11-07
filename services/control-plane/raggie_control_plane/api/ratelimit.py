# SPDX-License-Identifier: Apache-2.0

"""Brute-force protection for auth endpoints.

Two layers:

* a per-client-IP sliding window (in-process, per replica) keyed on the real
  client address — X-Forwarded-For is honoured only from TRUSTED_PROXY_CIDRS,
  so the web container's own address no longer puts every user in one bucket;
* a per-account progressive lockout after repeated failed logins, shared across
  replicas through Redis (in-process fallback when Redis is unavailable).
"""

from __future__ import annotations

import hashlib
import logging
import math
import time
from collections import defaultdict, deque
from typing import Protocol

from fastapi import HTTPException, Request, status
from redis.exceptions import RedisError

from raggie_control_plane.api.client_ip import client_ip
from raggie_control_plane.config import settings

log = logging.getLogger("control-plane.ratelimit")


class SlidingWindowLimiter:
    def __init__(self, max_events: int, window_seconds: float) -> None:
        self._max = max_events
        self._window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, now: float) -> bool:
        dq = self._hits[key]
        while dq and now - dq[0] > self._window:
            dq.popleft()
        if len(dq) >= self._max:
            return False
        dq.append(now)
        return True


_login_limiter = SlidingWindowLimiter(
    settings.auth_rate_limit_max, settings.auth_rate_limit_window_seconds
)


async def auth_rate_limit(request: Request) -> None:
    if not _login_limiter.allow(client_ip(request), time.monotonic()):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "too many authentication attempts; slow down",
            headers={"Retry-After": str(settings.auth_rate_limit_window_seconds)},
        )


# ── Per-account lockout ──────────────────────────────────────────────────────
class LockoutStore(Protocol):
    async def record_failure(self, key: str, now: float, window: int) -> int: ...
    async def lock_until(self, key: str) -> float: ...
    async def set_lock(self, key: str, until: float, ttl: int) -> None: ...
    async def clear(self, key: str) -> None: ...


class MemoryLockoutStore:
    """Single-replica fallback (and test) store."""

    def __init__(self) -> None:
        self._failures: dict[str, tuple[int, float]] = {}
        self._locks: dict[str, float] = {}

    async def record_failure(self, key: str, now: float, window: int) -> int:
        count, started = self._failures.get(key, (0, now))
        if now - started > window:
            count, started = 0, now
        self._failures[key] = (count + 1, started)
        return count + 1

    async def lock_until(self, key: str) -> float:
        return self._locks.get(key, 0.0)

    async def set_lock(self, key: str, until: float, ttl: int) -> None:
        self._locks[key] = until

    async def clear(self, key: str) -> None:
        self._failures.pop(key, None)
        self._locks.pop(key, None)


class RedisLockoutStore:
    _PREFIX = "raggie:auth:lockout"

    def __init__(self, redis) -> None:
        self._redis = redis

    async def record_failure(self, key: str, now: float, window: int) -> int:
        k = f"{self._PREFIX}:fail:{key}"
        count = int(await self._redis.incr(k))
        if count == 1:
            await self._redis.expire(k, window)
        return count

    async def lock_until(self, key: str) -> float:
        raw = await self._redis.get(f"{self._PREFIX}:lock:{key}")
        return float(raw) if raw else 0.0

    async def set_lock(self, key: str, until: float, ttl: int) -> None:
        await self._redis.set(f"{self._PREFIX}:lock:{key}", str(until), ex=max(ttl, 1))

    async def clear(self, key: str) -> None:
        await self._redis.delete(f"{self._PREFIX}:fail:{key}", f"{self._PREFIX}:lock:{key}")


class _FallbackStore:
    """Redis first; on a Redis outage degrade to the in-process store rather
    than failing logins (the IP limiter still applies)."""

    def __init__(self, primary: LockoutStore, fallback: LockoutStore) -> None:
        self._primary = primary
        self._fallback = fallback

    async def _call(self, name: str, *args):
        try:
            return await getattr(self._primary, name)(*args)
        except (RedisError, OSError) as exc:
            log.warning("login lockout: redis unavailable (%s); using in-process store", exc)
            return await getattr(self._fallback, name)(*args)

    async def record_failure(self, key: str, now: float, window: int) -> int:
        return await self._call("record_failure", key, now, window)

    async def lock_until(self, key: str) -> float:
        return await self._call("lock_until", key)

    async def set_lock(self, key: str, until: float, ttl: int) -> None:
        await self._call("set_lock", key, until, ttl)

    async def clear(self, key: str) -> None:
        await self._call("clear", key)


class LoginLockout:
    """After ``threshold`` failures within ``window`` seconds an account is
    locked for ``base`` seconds, doubling with each further failure up to
    ``cap``. Keyed on a hash of the normalized email, so unknown accounts are
    treated identically (no account enumeration)."""

    def __init__(
        self, store: LockoutStore, *, threshold: int, window: int, base: int, cap: int
    ) -> None:
        self._store = store
        self._threshold = max(threshold, 1)
        self._window = window
        self._base = base
        self._cap = cap

    @staticmethod
    def _key(email: str) -> str:
        return hashlib.sha256(email.strip().lower().encode()).hexdigest()

    async def retry_after(self, email: str, now: float) -> int:
        remaining = await self._store.lock_until(self._key(email)) - now
        return math.ceil(remaining) if remaining > 0 else 0

    async def register_failure(self, email: str, now: float) -> int:
        """Record a failed attempt; returns the lock duration it triggered (0 =
        not locked yet)."""
        key = self._key(email)
        count = await self._store.record_failure(key, now, self._window)
        if count < self._threshold:
            return 0
        duration = min(self._cap, self._base * 2 ** (count - self._threshold))
        await self._store.set_lock(key, now + duration, max(duration, self._window))
        return duration

    async def reset(self, email: str) -> None:
        await self._store.clear(self._key(email))


_memory_lockout_store = MemoryLockoutStore()


def login_lockout(request: Request) -> LoginLockout:
    redis = getattr(request.app.state, "redis", None)
    store: LockoutStore = (
        _FallbackStore(RedisLockoutStore(redis), _memory_lockout_store)
        if redis is not None
        else _memory_lockout_store
    )
    return LoginLockout(
        store,
        threshold=settings.login_lockout_threshold,
        window=settings.login_lockout_window_seconds,
        base=settings.login_lockout_base_seconds,
        cap=settings.login_lockout_max_seconds,
    )
