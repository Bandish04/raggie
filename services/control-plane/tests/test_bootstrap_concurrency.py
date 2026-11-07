# SPDX-License-Identifier: Apache-2.0

"""Concurrent first-run bootstraps on separate, committing connections: exactly
one caller becomes the first super admin, the rest get 409."""

import asyncio
import uuid

import asyncpg
import httpx
import pytest
from httpx import ASGITransport

from raggie_control_plane.api.deps import get_conn
from raggie_control_plane.config import settings
from raggie_control_plane.db.migrate import apply_migrations
from raggie_control_plane.db.pool import create_pool
from raggie_control_plane.main import app

CALLERS = 4


@pytest.fixture
async def fresh_install():
    """A pool on an isolated, fully migrated schema: a never-bootstrapped install
    whose commits are real (the shared `conn` fixture rolls back and is one
    connection, so it cannot race)."""
    schema = f"boot_{uuid.uuid4().hex[:12]}"
    admin = await asyncpg.connect(settings.dsn)
    await admin.execute(f'CREATE SCHEMA "{schema}"')
    sep = "&" if "?" in settings.dsn else "?"
    # public stays on the path for extension functions (pgcrypto).
    pool = await create_pool(f"{settings.dsn}{sep}search_path={schema}%2Cpublic")
    try:
        async with pool.acquire() as c:
            await apply_migrations(c, settings.migrations_dir)
        yield pool
    finally:
        await pool.close()
        await admin.execute(f'DROP SCHEMA "{schema}" CASCADE')
        await admin.close()


@pytest.mark.requires_postgres
async def test_concurrent_bootstraps_create_exactly_one_super_admin(fresh_install) -> None:
    async def _own_connection():
        async with fresh_install.acquire() as c:
            yield c

    app.dependency_overrides[get_conn] = _own_connection
    try:
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            responses = await asyncio.gather(
                *(
                    client.post(
                        "/api/v1/onboarding/bootstrap",
                        json={
                            "email": f"admin{i}@race.test",
                            "password": "pw-1234567890",
                            "org_name": f"Race {i}",
                        },
                    )
                    for i in range(CALLERS)
                )
            )
    finally:
        app.dependency_overrides.clear()

    codes = sorted(r.status_code for r in responses)
    assert codes == [201] + [409] * (CALLERS - 1)
    async with fresh_install.acquire() as c:
        admins = await c.fetchval("SELECT count(*) FROM users WHERE role = 'SUPER_ADMIN'")
        orgs = await c.fetchval("SELECT count(*) FROM organizations")
    assert (admins, orgs) == (1, 1)
