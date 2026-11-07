# SPDX-License-Identifier: Apache-2.0

import os

# Point tests at the local disposable Postgres unless overridden (CI sets this to
# the workflow's postgres service). Must run before importing the app/config.
os.environ.setdefault("DATABASE_URL", "postgresql://raggie:raggie@localhost:55432/raggie")
os.environ.setdefault("RUN_MIGRATIONS_ON_BOOT", "true")
# An unset RAGGIE_ENV means production (strict secrets, setup token required);
# the suite runs as "test", which keeps the dev defaults usable.
os.environ.setdefault("RAGGIE_ENV", "test")
# The disposable test Redis, so lifespan-backed clients never try to resolve the
# compose-only "redis" hostname. REDIS_TEST_URL is what CI and
# `make test-integration` export (shared with the workers suite); the fallback
# is scripts/test_deps.sh's port.
os.environ.setdefault("REDIS_URL", os.environ.get("REDIS_TEST_URL", "redis://localhost:56379"))
# The embeddings gateway is never real in tests: the `gateway` fixture mocks it.
os.environ.setdefault("EMBEDDINGS_BASE_URL", "http://embeddings.test/v1")

from collections.abc import AsyncIterator, Iterator  # noqa: E402

import asyncpg  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
import respx  # noqa: E402
from _infra import Dependency, InfraGate  # noqa: E402
from embeddings_stub import LEGACY_INFO  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from raggie_control_plane.config import settings  # noqa: E402
from raggie_control_plane.db.migrate import apply_migrations  # noqa: E402
from raggie_control_plane.db.pool import create_pool  # noqa: E402
from raggie_control_plane.main import app  # noqa: E402


@pytest_asyncio.fixture
async def conn() -> AsyncIterator[asyncpg.Connection]:
    """A connection inside a rolled-back transaction for per-test isolation.

    Migrations are applied once (committed); each test's data is rolled back.
    """
    pool = await create_pool()
    try:
        async with pool.acquire() as c:
            await apply_migrations(c, settings.migrations_dir)
        async with pool.acquire() as c:
            tx = c.transaction()
            await tx.start()
            try:
                yield c
            finally:
                await tx.rollback()
    finally:
        await pool.close()


@pytest.fixture
def gateway() -> Iterator[respx.MockRouter]:
    """The embeddings gateway, mocked: GET /info answers the legacy profile.
    Tests re-point ``gateway.routes["info"]`` to simulate a new profile or an
    outage."""
    with respx.mock(base_url=settings.embeddings_base_url, assert_all_called=False) as router:
        router.get("/info", name="info").respond(json=LEGACY_INFO)
        yield router


@pytest.fixture
def client(gateway) -> AsyncIterator[TestClient]:
    """TestClient as a context manager so the app lifespan (pool + migrations) runs."""
    with TestClient(app) as c:
        yield c


# Datastore-backed tests skip with a reason when the disposable test deps are
# down (fail under CI=true). The app lifespan (`client`) needs Postgres and
# publishes events / rate-limits through Redis, so it maps to both.
INFRA = InfraGate(
    [
        Dependency(
            "postgres",
            "Postgres",
            "DATABASE_URL",
            lambda: os.environ.get("DATABASE_URL", ""),
            frozenset({"conn", "client", "scratch_schema"}),
        ),
        Dependency(
            "redis",
            "Redis",
            "REDIS_URL",
            lambda: os.environ.get("REDIS_URL", ""),
            frozenset({"client"}),
        ),
        Dependency(
            "s3",
            "S3 object store",
            "OBJECTSTORE_TEST_ENDPOINT",
            lambda: os.environ.get("OBJECTSTORE_TEST_ENDPOINT", ""),
            frozenset(),
            optional=True,
        ),
    ]
)


def pytest_configure(config) -> None:
    INFRA.configure(config)


def pytest_collection_modifyitems(config, items) -> None:
    INFRA.mark(items)
    # RAGGIE_TEST_REVERSE=1 runs the suite back to front, to catch tests that
    # depend on state an earlier test committed.
    if os.environ.get("RAGGIE_TEST_REVERSE") == "1":
        items.reverse()


def pytest_runtest_setup(item) -> None:
    INFRA.check(item)
