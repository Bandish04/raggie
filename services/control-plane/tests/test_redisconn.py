# SPDX-License-Identifier: Apache-2.0

"""Redis client selection: Sentinel (HA) vs REDIS_URL, mirroring the edge."""

import pytest
from redis.asyncio.sentinel import Sentinel, SentinelConnectionPool

from raggie_control_plane.config import (
    InsecureConfigurationError,
    Settings,
    validate_runtime_secrets,
)
from raggie_control_plane.infra.redisconn import (
    MODE_SENTINEL,
    MODE_URL,
    RedisConfigError,
    create_redis,
)


def _cfg(**kw) -> Settings:
    base = {"raggie_env": "development", "redis_url": "redis://cache:6379/0"}
    base.update(kw)
    return Settings(_env_file=None, **base)


async def test_url_mode_uses_redis_url() -> None:
    conn = create_redis(_cfg(redis_url="redis://cache:6380/2"))
    try:
        assert conn.mode == MODE_URL and conn.sentinel is None
        kw = conn.client.connection_pool.connection_kwargs
        assert (kw["host"], kw["port"], kw["db"]) == ("cache", 6380, 2)
        assert kw.get("password") is None
    finally:
        await conn.aclose()


async def test_url_mode_password_fills_in_only_when_url_has_none() -> None:
    conn = create_redis(_cfg(redis_password="from-env"))
    assert conn.client.connection_pool.connection_kwargs["password"] == "from-env"
    await conn.aclose()
    conn = create_redis(_cfg(redis_url="redis://:in-url@cache:6379", redis_password="from-env"))
    assert conn.client.connection_pool.connection_kwargs["password"] == "in-url"
    await conn.aclose()


async def test_sentinel_mode_ignores_redis_url() -> None:
    conn = create_redis(
        _cfg(
            redis_url="redis://ignored:1",
            redis_sentinel_addrs="s0:26379, s1:26380",
            redis_sentinel_master="raggie",
            redis_password="data-pw",
            redis_sentinel_password="sentinel-pw",
            redis_db=3,
        )
    )
    try:
        assert conn.mode == MODE_SENTINEL
        assert isinstance(conn.sentinel, Sentinel)
        kws = [s.connection_pool.connection_kwargs for s in conn.sentinel.sentinels]
        addrs = [(kw["host"], kw["port"]) for kw in kws]
        assert addrs == [("s0", 26379), ("s1", 26380)]
        assert conn.sentinel.sentinel_kwargs == {"password": "sentinel-pw"}
        pool = conn.client.connection_pool
        assert isinstance(pool, SentinelConnectionPool) and pool.service_name == "raggie"
        assert pool.connection_kwargs["password"] == "data-pw"
        assert pool.connection_kwargs["db"] == 3
    finally:
        await conn.aclose()


async def test_sentinel_without_sentinel_password_sends_none() -> None:
    conn = create_redis(_cfg(redis_sentinel_addrs="s0:26379", redis_sentinel_master="m"))
    try:
        assert "password" not in conn.sentinel.sentinel_kwargs
        assert conn.client.connection_pool.connection_kwargs.get("password") is None
    finally:
        await conn.aclose()


@pytest.mark.parametrize("env", ["development", "production"])
@pytest.mark.parametrize(
    "half",
    [{"redis_sentinel_addrs": "s0:26379"}, {"redis_sentinel_master": "raggie"}],
)
def test_half_configured_sentinel_fails_in_every_env(env, half) -> None:
    cfg = Settings(
        _env_file=None,
        raggie_env=env,
        jwt_secret="j" * 48,
        widget_token_secret="w" * 48,
        minio_root_password="m1n10-Str0ng-Passw0rd",
        database_url="postgresql://u:Str0ng-Postgres-Passw0rd@db/x",
        **half,
    )
    with pytest.raises(InsecureConfigurationError, match="REDIS_SENTINEL_ADDRS"):
        validate_runtime_secrets(cfg)


def test_invalid_url_error_never_echoes_credentials() -> None:
    with pytest.raises(RedisConfigError) as exc:
        create_redis(_cfg(redis_url="http://user:hunter2-secret@cache:6379"))
    assert "hunter2-secret" not in str(exc.value) and "REDIS_URL" in str(exc.value)
    assert exc.value.__cause__ is None
    with pytest.raises(RedisConfigError) as exc:
        create_redis(_cfg(redis_url="redis://:hunter2-secret@cache:notaport"))
    assert "hunter2-secret" not in str(exc.value)
    assert exc.value.__cause__ is None and exc.value.__suppress_context__


@pytest.mark.parametrize("addrs", ["s0", "s0:notaport", ":26379", "s0:0", "s0:70000"])
def test_invalid_sentinel_addrs_rejected(addrs) -> None:
    with pytest.raises(RedisConfigError, match="REDIS_SENTINEL_ADDRS"):
        create_redis(_cfg(redis_sentinel_addrs=addrs, redis_sentinel_master="m"))


def test_redis_db_is_clamped() -> None:
    assert _cfg(redis_db=5000).redis_db_clamped == 1024
    assert _cfg(redis_db=-1).redis_db_clamped == 0
