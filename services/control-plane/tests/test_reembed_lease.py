# SPDX-License-Identifier: Apache-2.0

"""One re-embed at a time across replicas, also behind a transaction pooler
(Helm ``postgresql.cnpg.pooler``, PgBouncer ``pool_mode=transaction``): every
statement may reach another backend, so a session advisory lock taken on one
backend and released on another stays held forever. The guard is a lease row
in system_settings instead. These tests commit, so they run in a scratch schema
with the real migrations."""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import asyncpg
import pytest
import pytest_asyncio

from raggie_control_plane import reindex
from raggie_control_plane.config import settings
from raggie_control_plane.db.migrate import apply_migrations
from raggie_control_plane.db.pool import _init_connection
from raggie_control_plane.db.repositories import (
    DocumentRepo,
    OrganizationRepo,
    SettingsRepo,
    WorkspaceRepo,
)
from raggie_control_plane.embeddings_profile import (
    IngestTarget,
    ReembedBusyError,
    reembed_stale,
)

TARGET = IngestTarget("raggie_chunks_d768_5e1f00d2", "5e1f00d2", 768)


@pytest_asyncio.fixture
async def scratch_schema():
    """An isolated schema with the real migrations; dropped afterwards."""
    schema = f"lease_{uuid.uuid4().hex[:12]}"
    admin = await asyncpg.connect(settings.dsn)
    await admin.execute(f'CREATE SCHEMA "{schema}"')
    try:
        c = await _connect(schema)
        try:
            await apply_migrations(c, settings.migrations_dir)
        finally:
            await c.close()
        yield schema
    finally:
        await admin.execute(f'DROP SCHEMA "{schema}" CASCADE')
        await admin.close()


async def _connect(schema: str) -> asyncpg.Connection:
    c = await asyncpg.connect(settings.dsn, server_settings={"search_path": f"{schema}, public"})
    await _init_connection(c)
    return c


class RoundRobinConn:
    """A transaction pooler in miniature: each statement runs on the next
    backend."""

    def __init__(self, conns: list[asyncpg.Connection]) -> None:
        self._conns = conns
        self._i = 0

    def _next(self) -> asyncpg.Connection:
        self._i += 1
        return self._conns[self._i % len(self._conns)]

    async def execute(self, *args, **kw):
        return await self._next().execute(*args, **kw)

    async def fetch(self, *args, **kw):
        return await self._next().fetch(*args, **kw)

    async def fetchrow(self, *args, **kw):
        return await self._next().fetchrow(*args, **kw)

    async def fetchval(self, *args, **kw):
        return await self._next().fetchval(*args, **kw)


class Publisher:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def publish(self, topic: str, payload: dict) -> str:
        self.events.append(payload)
        return "1-0"


class GatedPublisher(Publisher):
    """Holds the first publish until released, so a run stays in progress."""

    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def publish(self, topic: str, payload: dict) -> str:
        self.started.set()
        await asyncio.wait_for(self.release.wait(), timeout=30)
        return await super().publish(topic, payload)


async def _stale_doc(c: asyncpg.Connection, name: str = "a.pdf") -> None:
    org = await OrganizationRepo(c).create(f"Org {uuid.uuid4().hex[:6]}")
    ws = await WorkspaceRepo(c).create(org.id, "Docs", "INTERNAL")
    await DocumentRepo(c).create(
        ws.id,
        name,
        1,
        "raggie_chunks_d1024",
        object_key=f"k/{name}",
        embedding_fingerprint="2872ae6a",
    )


@pytest_asyncio.fixture
async def conns(scratch_schema):
    cs = [await _connect(scratch_schema) for _ in range(3)]
    try:
        yield cs
    finally:
        for c in cs:
            await c.close()


async def test_a_run_behind_a_transaction_pooler_leaves_nothing_held(conns) -> None:
    c1, c2, c3 = conns
    await _stale_doc(c1)
    result = await reembed_stale(RoundRobinConn([c1, c2]), Publisher(), TARGET, trigger="test")
    assert result["reembedded"] == 1
    # A later run from a backend the first one never used is not blocked.
    await _stale_doc(c3, "b.pdf")
    again = await reembed_stale(c3, Publisher(), TARGET, trigger="test")
    assert again["reembedded"] == 1


async def test_two_concurrent_reembeds_one_is_busy(conns) -> None:
    c1, c2, _ = conns
    await _stale_doc(c1)
    gated = GatedPublisher()
    first = asyncio.create_task(reembed_stale(c1, gated, TARGET, trigger="test"))
    await asyncio.wait_for(gated.started.wait(), timeout=30)
    with pytest.raises(ReembedBusyError):
        await reembed_stale(c2, Publisher(), TARGET, trigger="test")
    gated.release.set()
    assert (await first)["reembedded"] == 1
    # Released: the next run goes through.
    assert (await reembed_stale(c2, Publisher(), TARGET, trigger="test"))["reembedded"] == 0


async def test_reindex_is_busy_while_a_reembed_runs(conns) -> None:
    c1, c2, _ = conns
    await _stale_doc(c1)
    gated = GatedPublisher()
    first = asyncio.create_task(reembed_stale(c1, gated, TARGET, trigger="test"))
    await asyncio.wait_for(gated.started.wait(), timeout=30)
    stored: list[str] = []

    async def get(force: bool = False):
        return SimpleNamespace(fingerprint="5e1f00d2", collection=TARGET.collection, dim=768)

    async def store(conn, info, *, expected, reason):
        stored.append(info.fingerprint)
        return True

    profile = SimpleNamespace(client=SimpleNamespace(get=get), store=store)
    try:
        with pytest.raises(reindex.ReindexBusyError):
            await reindex.reindex_all(c2, Publisher(), profile)
        assert stored == []  # the lease is taken before the profile is stored
    finally:
        gated.release.set()
        await first


async def test_an_expired_lease_is_taken_over_and_the_old_owner_loses_it(conns) -> None:
    c1, c2, c3 = conns
    a, b, c = SettingsRepo(c1), SettingsRepo(c2), SettingsRepo(c3)
    assert await a.acquire_reembed_lease("owner-a", 60)
    assert not await b.acquire_reembed_lease("owner-b", 60)
    # Refresh and release work from any backend (only the owner token matters).
    assert await b.refresh_reembed_lease("owner-a", 60)
    await c1.execute(
        "UPDATE system_settings SET reembed_lease_expires_at = now() - interval '1 second'"
    )
    assert await b.acquire_reembed_lease("owner-b", 60)
    assert not await a.refresh_reembed_lease("owner-a", 60)
    await a.release_reembed_lease("owner-a")  # not the owner any more: no-op
    assert not await c.acquire_reembed_lease("owner-c", 60)
    await c.release_reembed_lease("owner-b")
    assert await c.acquire_reembed_lease("owner-c", 60)
