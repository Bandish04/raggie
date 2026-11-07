# SPDX-License-Identifier: Apache-2.0

"""Redis client factory for the query cache.

Same selection as the edge (internal/redisconn), control-plane and workers: a
Sentinel-managed master when REDIS_SENTINEL_ADDRS and REDIS_SENTINEL_MASTER are
both set (follows master promotion; the URL is ignored), otherwise a plain
client from EMBEDDINGS_CACHE_REDIS_URL (falling back to REDIS_URL) with
REDIS_PASSWORD filled in when the URL carries none. Values are raw float32
bytes, so responses are not decoded. Short socket timeouts keep a dead cache
from slowing queries (the cache fails open). Clients are lazy.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

import redis.asyncio as aioredis
from redis.asyncio.sentinel import Sentinel

from raggie_embeddings.config import Settings

MODE_URL = "url"
MODE_SENTINEL = "sentinel"

_URL_SCHEMES = {"redis", "rediss", "unix"}


class RedisConfigError(ValueError):
    """Unusable Redis settings. Messages never include credentials."""


@dataclass
class RedisConnection:
    client: aioredis.Redis
    mode: str
    sentinel: Sentinel | None = None

    async def aclose(self) -> None:
        await self.client.aclose()
        if self.sentinel is not None:
            for node in self.sentinel.sentinels:
                await node.aclose()


def _sentinel_addrs(raw: str) -> list[tuple[str, int]]:
    addrs: list[tuple[str, int]] = []
    for part in raw.split(","):
        entry = part.strip()
        if not entry:
            continue  # empties dropped, like the edge's getenvList
        host, sep, port = entry.rpartition(":")
        if not sep or not host or not port.isdigit() or not 0 < int(port) < 65536:
            raise RedisConfigError("invalid REDIS_SENTINEL_ADDRS entry (expected host:port)")
        addrs.append((host, int(port)))
    if not addrs:
        raise RedisConfigError("REDIS_SENTINEL_ADDRS has no host:port entries")
    return addrs


def create_redis(cfg: Settings) -> RedisConnection:
    timeouts = {
        "socket_connect_timeout": cfg.embeddings_cache_timeout_seconds,
        "socket_timeout": cfg.embeddings_cache_timeout_seconds,
    }
    if cfg.redis_sentinel_enabled:
        sentinel_kwargs = dict(timeouts)
        if cfg.redis_sentinel_password:
            sentinel_kwargs["password"] = cfg.redis_sentinel_password
        sentinel = Sentinel(
            _sentinel_addrs(cfg.redis_sentinel_addrs),
            sentinel_kwargs=sentinel_kwargs,
            **timeouts,
        )
        client = sentinel.master_for(
            cfg.redis_sentinel_master.strip(),
            password=cfg.redis_password or None,
            db=cfg.redis_db_clamped,
            **timeouts,
        )
        return RedisConnection(client=client, mode=MODE_SENTINEL, sentinel=sentinel)

    url = cfg.embeddings_cache_redis_url.strip()
    try:
        parsed = urlsplit(url)
        has_password = bool(parsed.password)
    except ValueError:
        parsed, has_password = None, False
    if parsed is None or parsed.scheme not in _URL_SCHEMES:
        # The URL may embed a password: keep the message generic.
        raise RedisConfigError(
            "invalid EMBEDDINGS_CACHE_REDIS_URL/REDIS_URL (expected redis:// or rediss://)"
        )
    kwargs: dict = dict(timeouts)
    if not has_password and cfg.redis_password:
        kwargs["password"] = cfg.redis_password
    try:
        client = aioredis.from_url(url, **kwargs)
    except ValueError:
        # `from None`: the chained parser error could quote the URL (password).
        raise RedisConfigError(
            "invalid EMBEDDINGS_CACHE_REDIS_URL/REDIS_URL (expected redis:// or rediss://)"
        ) from None
    return RedisConnection(client=client, mode=MODE_URL)
