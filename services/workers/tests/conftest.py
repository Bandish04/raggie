# SPDX-License-Identifier: Apache-2.0

import os
import re
from collections.abc import AsyncIterator
from pathlib import Path

# Local disposable infra defaults unless overridden (CI sets these to services).
os.environ.setdefault("QDRANT_TEST_URL", "http://localhost:56333")
os.environ.setdefault("REDIS_TEST_URL", "redis://localhost:56379")
os.environ.setdefault("DATABASE_URL", "postgresql://raggie:raggie@localhost:55432/raggie")

import asyncpg  # noqa: E402
import pytest_asyncio  # noqa: E402
import redis.asyncio as aioredis  # noqa: E402
from _infra import Dependency, InfraGate  # noqa: E402
from qdrant_client import AsyncQdrantClient  # noqa: E402

from raggie_workers.ingestion.vectorstore import QdrantVectorStore  # noqa: E402

# Datastore-backed tests skip with a reason when the disposable test deps are
# down (fail under CI=true). Fixtures below map a test to its dependencies.
INFRA = InfraGate(
    [
        Dependency(
            "postgres",
            "Postgres",
            "DATABASE_URL",
            lambda: os.environ.get("DATABASE_URL", ""),
            frozenset({"pg_pool"}),
        ),
        Dependency(
            "redis",
            "Redis",
            "REDIS_TEST_URL",
            lambda: os.environ.get("REDIS_TEST_URL", ""),
            frozenset({"redis_client", "bus"}),
        ),
        Dependency(
            "qdrant",
            "Qdrant",
            "QDRANT_TEST_URL",
            lambda: os.environ.get("QDRANT_TEST_URL", ""),
            frozenset({"qdrant_store"}),
        ),
    ]
)


def pytest_configure(config) -> None:
    INFRA.configure(config)


def pytest_collection_modifyitems(config, items) -> None:
    INFRA.mark(items)


def pytest_runtest_setup(item) -> None:
    INFRA.check(item)


# Canonical migrations live in the control-plane service (single DDL owner).
_MIGRATIONS = Path(__file__).resolve().parents[3] / "services" / "control-plane" / "migrations"
_UP_RE = re.compile(r"^(\d+)_.*\.up\.sql$")


def _version_num(path: Path) -> int:
    m = _UP_RE.match(path.name)
    assert m is not None
    return int(m.group(1))


async def _apply_migrations(conn: asyncpg.Connection) -> None:
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
    )
    applied = {r["version"] for r in await conn.fetch("SELECT version FROM schema_migrations")}
    for path in sorted(_MIGRATIONS.glob("*.up.sql"), key=_version_num):
        version = f"{_version_num(path):04d}"
        if version in applied:
            continue
        async with conn.transaction():
            await conn.execute(path.read_text(encoding="utf-8"))
            await conn.execute("INSERT INTO schema_migrations(version) VALUES($1)", version)


@pytest_asyncio.fixture
async def qdrant_store() -> AsyncIterator[QdrantVectorStore]:
    client = AsyncQdrantClient(url=os.environ["QDRANT_TEST_URL"])
    try:
        yield QdrantVectorStore(client)
    finally:
        await client.close()


@pytest_asyncio.fixture
async def redis_client() -> AsyncIterator[aioredis.Redis]:
    client = aioredis.from_url(os.environ["REDIS_TEST_URL"], decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()


@pytest_asyncio.fixture
async def pg_pool() -> AsyncIterator[asyncpg.Pool]:
    pool = await asyncpg.create_pool(
        dsn=os.environ["DATABASE_URL"], min_size=1, max_size=4, statement_cache_size=0
    )
    try:
        async with pool.acquire() as conn:
            await _apply_migrations(conn)
        yield pool
    finally:
        await pool.close()
