# SPDX-License-Identifier: Apache-2.0

"""The control plane's single Redis client factory.

Mirrors the edge (internal/redisconn): a Sentinel-managed master when
REDIS_SENTINEL_ADDRS and REDIS_SENTINEL_MASTER are both set (HA — follows
master promotion; REDIS_URL is ignored), otherwise a plain client from
REDIS_URL with REDIS_PASSWORD filled in when the URL carries none. Every Redis
user here (event publisher, login lockout) shares the client built once at
boot. Clients are lazy: nothing connects until the first command.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

import redis.asyncio as aioredis
from redis.asyncio.sentinel import Sentinel

from raggie_control_plane.config import Settings

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
    if cfg.redis_sentinel_enabled:
        sentinel = Sentinel(
            _sentinel_addrs(cfg.redis_sentinel_addrs),
            sentinel_kwargs=(
                {"password": cfg.redis_sentinel_password} if cfg.redis_sentinel_password else {}
            ),
        )
        client = sentinel.master_for(
            cfg.redis_sentinel_master.strip(),
            password=cfg.redis_password or None,
            db=cfg.redis_db_clamped,
        )
        return RedisConnection(client=client, mode=MODE_SENTINEL, sentinel=sentinel)

    try:
        parsed = urlsplit(cfg.redis_url.strip())
        has_password = bool(parsed.password)
    except ValueError:
        parsed, has_password = None, False
    if parsed is None or parsed.scheme not in _URL_SCHEMES:
        # The URL may embed a password: keep the message generic.
        raise RedisConfigError("invalid REDIS_URL (expected redis:// or rediss://)")
    kwargs = {}
    if not has_password and cfg.redis_password:
        kwargs["password"] = cfg.redis_password
    try:
        client = aioredis.from_url(cfg.redis_url.strip(), **kwargs)
    except ValueError:
        # `from None`: the chained parser error could quote the URL (password).
        raise RedisConfigError("invalid REDIS_URL (expected redis:// or rediss://)") from None
    return RedisConnection(client=client, mode=MODE_URL)
