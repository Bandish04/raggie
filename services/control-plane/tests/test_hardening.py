# SPDX-License-Identifier: Apache-2.0

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport
from starlette.requests import Request

from raggie_control_plane.api import ratelimit
from raggie_control_plane.api.client_ip import client_ip, is_https
from raggie_control_plane.api.deps import get_conn
from raggie_control_plane.api.ratelimit import (
    LoginLockout,
    MemoryLockoutStore,
    SlidingWindowLimiter,
)
from raggie_control_plane.auth.service import AuthService
from raggie_control_plane.infra.secrets import resolve_secret
from raggie_control_plane.main import app


def test_sliding_window_limiter_blocks_over_max():
    lim = SlidingWindowLimiter(max_events=2, window_seconds=60)
    assert lim.allow("ip", 0.0) is True
    assert lim.allow("ip", 0.1) is True
    assert lim.allow("ip", 0.2) is False  # third within the window -> blocked
    # A different client is independent.
    assert lim.allow("other", 0.2) is True


def test_sliding_window_limiter_recovers_after_window():
    lim = SlidingWindowLimiter(max_events=1, window_seconds=10)
    assert lim.allow("ip", 0.0) is True
    assert lim.allow("ip", 5.0) is False
    assert lim.allow("ip", 11.0) is True  # window elapsed


def test_resolve_secret_prefers_file(tmp_path, monkeypatch):
    secret_file = tmp_path / "jwt"
    secret_file.write_text("super-secret-from-file\n", encoding="utf-8")
    monkeypatch.setenv("JWT_SECRET_FILE", str(secret_file))
    assert resolve_secret("JWT_SECRET", "env-default") == "super-secret-from-file"


def test_resolve_secret_falls_back_to_current(monkeypatch):
    monkeypatch.delenv("WIDGET_TOKEN_SECRET_FILE", raising=False)
    assert resolve_secret("WIDGET_TOKEN_SECRET", "the-env-value") == "the-env-value"


# ── Real client IP behind trusted proxies ────────────────────────────────────
def _req(peer: str, xff: str | None = None, proto: str | None = None) -> Request:
    headers = []
    if xff is not None:
        headers.append((b"x-forwarded-for", xff.encode()))
    if proto is not None:
        headers.append((b"x-forwarded-proto", proto.encode()))
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": headers,
            "client": (peer, 5555),
            "scheme": "http",
            "server": ("cp", 8000),
        }
    )


def test_client_ip_ignores_forwarded_for_from_untrusted_peer() -> None:
    assert client_ip(_req("203.0.113.9", xff="1.2.3.4")) == "203.0.113.9"
    assert not is_https(_req("203.0.113.9", proto="https"))


def test_client_ip_uses_forwarded_for_from_trusted_proxy() -> None:
    # The web container (private range) forwards the browser's address.
    assert client_ip(_req("172.18.0.5", xff="198.51.100.7")) == "198.51.100.7"
    # A client-supplied left-most entry can't override what our proxy appended.
    assert client_ip(_req("172.18.0.5", xff="6.6.6.6, 198.51.100.7")) == "198.51.100.7"
    # Multiple trusted hops (ingress -> web) are skipped.
    assert client_ip(_req("172.18.0.5", xff="198.51.100.7, 10.0.0.2")) == "198.51.100.7"
    assert client_ip(_req("172.18.0.5")) == "172.18.0.5"
    assert is_https(_req("172.18.0.5", proto="https"))


async def test_ip_limiter_keys_on_real_client_not_proxy(monkeypatch) -> None:
    monkeypatch.setattr(ratelimit, "_login_limiter", SlidingWindowLimiter(1, 60))
    await ratelimit.auth_rate_limit(_req("172.18.0.5", xff="198.51.100.1"))
    # A different browser behind the same web container is not locked out.
    await ratelimit.auth_rate_limit(_req("172.18.0.5", xff="198.51.100.2"))
    with pytest.raises(Exception) as exc:
        await ratelimit.auth_rate_limit(_req("172.18.0.5", xff="198.51.100.1"))
    assert getattr(exc.value, "status_code", None) == 429


# ── Per-account progressive lockout ──────────────────────────────────────────
async def test_lockout_after_threshold_and_progressive_backoff() -> None:
    lock = LoginLockout(MemoryLockoutStore(), threshold=3, window=900, base=30, cap=100)
    for _ in range(2):
        assert await lock.register_failure("a@x.test", now=0.0) == 0
    assert await lock.retry_after("a@x.test", now=0.0) == 0
    assert await lock.register_failure("a@x.test", now=0.0) == 30  # threshold hit
    assert await lock.retry_after("a@x.test", now=10.0) == 20
    assert await lock.retry_after("other@x.test", now=10.0) == 0  # per account
    assert await lock.register_failure("a@x.test", now=31.0) == 60  # doubles
    assert await lock.register_failure("a@x.test", now=92.0) == 100  # capped
    await lock.reset("a@x.test")
    assert await lock.retry_after("a@x.test", now=92.0) == 0


async def test_lockout_is_case_insensitive_on_email() -> None:
    lock = LoginLockout(MemoryLockoutStore(), threshold=1, window=900, base=30, cap=900)
    await lock.register_failure("Admin@X.test", now=0.0)
    assert await lock.retry_after("admin@x.test", now=1.0) > 0


@pytest_asyncio.fixture
async def login_api(conn, monkeypatch):
    monkeypatch.setattr(ratelimit, "_login_limiter", SlidingWindowLimiter(1000, 60))
    monkeypatch.setattr(ratelimit, "_memory_lockout_store", MemoryLockoutStore(), raising=True)
    monkeypatch.setattr(ratelimit.settings, "login_lockout_threshold", 3)
    # A previous lifespan-backed test may have left a Redis client on app.state;
    # pin this test to the in-process store so it is hermetic.
    if hasattr(app.state, "redis"):
        monkeypatch.delattr(app.state, "redis")

    async def _conn_override():
        yield conn

    app.dependency_overrides[get_conn] = _conn_override
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c, conn
    app.dependency_overrides.clear()


async def test_login_locks_account_after_repeated_failures(login_api) -> None:
    client, conn = login_api
    await AuthService(conn).register("victim@x.test", "right-password", "STAFF")
    await AuthService(conn).register("bystander@x.test", "right-password", "STAFF")
    bad = {"email": "victim@x.test", "password": "wrong"}
    for _ in range(3):
        assert (await client.post("/api/v1/auth/login", json=bad)).status_code == 401
    good = {"email": "victim@x.test", "password": "right-password"}
    r = await client.post("/api/v1/auth/login", json=good)
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0
    # Other accounts (same IP / same web container) keep working.
    r = await client.post(
        "/api/v1/auth/login", json={"email": "bystander@x.test", "password": "right-password"}
    )
    assert r.status_code == 200


@pytest.mark.requires_redis
async def test_redis_lockout_store_shares_state_across_replicas() -> None:
    import os
    import uuid

    import redis.asyncio as aioredis

    from raggie_control_plane.api.ratelimit import RedisLockoutStore

    client = aioredis.from_url(os.environ["REDIS_URL"])
    email = f"{uuid.uuid4()}@x.test"
    replica_a = LoginLockout(RedisLockoutStore(client), threshold=2, window=60, base=30, cap=60)
    replica_b = LoginLockout(RedisLockoutStore(client), threshold=2, window=60, base=30, cap=60)
    try:
        await replica_a.register_failure(email, now=1000.0)
        assert await replica_b.register_failure(email, now=1000.0) == 30
        assert await replica_a.retry_after(email, now=1010.0) == 20
        await replica_b.reset(email)
        assert await replica_a.retry_after(email, now=1010.0) == 0
    finally:
        await replica_a.reset(email)
        await client.aclose()
