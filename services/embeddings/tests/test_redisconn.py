# SPDX-License-Identifier: Apache-2.0

"""The query cache's Redis client: same Sentinel/URL semantics as the edge,
control-plane and workers (binary values, so no response decoding)."""

import pytest
from conftest import make_settings
from fakes import local_stub_app, wait_ready
from fastapi.testclient import TestClient
from redis.asyncio.sentinel import Sentinel, SentinelConnectionPool

from raggie_embeddings.config import ConfigError
from raggie_embeddings.providers.redisconn import (
    MODE_SENTINEL,
    MODE_URL,
    RedisConfigError,
    create_redis,
)


async def test_url_mode_from_cache_url_with_password_fallback() -> None:
    conn = create_redis(
        make_settings(embeddings_cache_redis_url="redis://cache:6380/2", redis_password="from-env")
    )
    try:
        assert conn.mode == MODE_URL and conn.sentinel is None
        kw = conn.client.connection_pool.connection_kwargs
        assert (kw["host"], kw["port"], kw["db"], kw["password"]) == ("cache", 6380, 2, "from-env")
        assert not kw.get("decode_responses")  # float32 bytes
        # A dead cache must not slow queries down: short socket timeouts.
        assert (kw["socket_connect_timeout"], kw["socket_timeout"]) == (0.5, 0.5)
    finally:
        await conn.aclose()
    conn = create_redis(
        make_settings(
            embeddings_cache_redis_url="redis://:in-url@cache:6379", redis_password="from-env"
        )
    )
    assert conn.client.connection_pool.connection_kwargs["password"] == "in-url"
    await conn.aclose()


def test_redis_url_env_is_the_cache_fallback(monkeypatch) -> None:
    monkeypatch.setenv("REDIS_URL", "redis://shared:6379/0")
    assert make_settings().embeddings_cache_redis_url == "redis://shared:6379/0"


async def test_sentinel_mode_ignores_url() -> None:
    conn = create_redis(
        make_settings(
            embeddings_cache_redis_url="redis://ignored:1",
            redis_sentinel_addrs="s0:26379, s1:26380",
            redis_sentinel_master="raggie",
            redis_password="data-pw",
            redis_sentinel_password="sentinel-pw",
            redis_db=3,
        )
    )
    try:
        assert conn.mode == MODE_SENTINEL and isinstance(conn.sentinel, Sentinel)
        kws = [s.connection_pool.connection_kwargs for s in conn.sentinel.sentinels]
        assert [(kw["host"], kw["port"]) for kw in kws] == [("s0", 26379), ("s1", 26380)]
        assert conn.sentinel.sentinel_kwargs == {
            "password": "sentinel-pw",
            "socket_connect_timeout": 0.5,
            "socket_timeout": 0.5,
        }
        pool = conn.client.connection_pool
        assert isinstance(pool, SentinelConnectionPool) and pool.service_name == "raggie"
        assert (pool.connection_kwargs["password"], pool.connection_kwargs["db"]) == ("data-pw", 3)
    finally:
        await conn.aclose()


@pytest.mark.parametrize(
    "half", [{"redis_sentinel_addrs": "s0:26379"}, {"redis_sentinel_master": "raggie"}]
)
def test_half_configured_sentinel_refuses_to_boot(half) -> None:
    with pytest.raises(ConfigError, match="REDIS_SENTINEL_ADDRS"):
        make_settings(**half).validate_for_boot()
    with pytest.raises(ConfigError, match="REDIS_SENTINEL_ADDRS"):
        with TestClient(local_stub_app(make_settings(**half))):
            pass


def test_invalid_url_error_never_echoes_credentials() -> None:
    with pytest.raises(RedisConfigError) as exc:
        create_redis(make_settings(embeddings_cache_redis_url="http://u:hunter2-secret@c:6379"))
    assert "hunter2-secret" not in str(exc.value) and exc.value.__cause__ is None
    with pytest.raises(RedisConfigError) as exc:
        create_redis(make_settings(embeddings_cache_redis_url="redis://:hunter2-secret@c:x"))
    assert "hunter2-secret" not in str(exc.value) and exc.value.__suppress_context__


@pytest.mark.parametrize("addrs", ["s0", "s0:notaport", ":26379", "s0:0", "s0:70000"])
def test_invalid_sentinel_addrs_rejected(addrs) -> None:
    with pytest.raises(RedisConfigError, match="REDIS_SENTINEL_ADDRS"):
        create_redis(make_settings(redis_sentinel_addrs=addrs, redis_sentinel_master="m"))


def test_gateway_builds_its_cache_through_the_factory(monkeypatch) -> None:
    import raggie_embeddings.main as main_module

    built = []
    real = main_module.create_redis

    def spy(cfg):
        conn = real(cfg)
        built.append(conn.mode)
        return conn

    monkeypatch.setattr(main_module, "create_redis", spy)
    cfg = make_settings(redis_sentinel_addrs="s0:26379", redis_sentinel_master="raggie")
    with TestClient(local_stub_app(cfg)) as client:
        wait_ready(client)  # Sentinel unreachable: cache fails open, queries still work
        assert client.post("/v1/query", json={"query": "q"}).status_code == 200
    assert built == [MODE_SENTINEL]
