# SPDX-License-Identifier: Apache-2.0

"""HA-safe migrations: concurrent appliers, CLI entrypoint, readiness gating."""

import asyncio
import os
import subprocess
import sys
import uuid
from pathlib import Path

import asyncpg
import pytest
from fastapi.testclient import TestClient

from raggie_control_plane.config import settings
from raggie_control_plane.db.migrate import apply_migrations, pending_migrations
from raggie_control_plane.main import app

_ROOT = Path(__file__).resolve().parent.parent


def _write(dirpath: Path, files: dict[str, str]) -> None:
    for name, sql in files.items():
        (dirpath / name).write_text(sql, encoding="utf-8")


@pytest.fixture
async def scratch_schema():
    """An isolated schema (own schema_migrations) so nothing touches public."""
    schema = f"mig_{uuid.uuid4().hex[:12]}"
    admin = await asyncpg.connect(settings.dsn)
    await admin.execute(f'CREATE SCHEMA "{schema}"')
    try:
        yield schema
    finally:
        await admin.execute(f'DROP SCHEMA "{schema}" CASCADE')
        await admin.close()


async def _connect(schema: str) -> asyncpg.Connection:
    return await asyncpg.connect(settings.dsn, server_settings={"search_path": schema})


async def test_concurrent_appliers_apply_each_migration_once(scratch_schema, tmp_path) -> None:
    # Non-idempotent DDL + a sleep to widen the race window: without a lock the
    # second runner re-executes 0001 and fails with "relation already exists".
    _write(
        tmp_path,
        {
            "0001_a.up.sql": "SELECT pg_sleep(0.3); CREATE TABLE t_a (id int);",
            "0002_b.up.sql": "CREATE TABLE t_b (id int);",
            "0003_c.up.sql": "CREATE TABLE t_c (id int);",
        },
    )
    c1, c2 = await _connect(scratch_schema), await _connect(scratch_schema)
    try:
        r1, r2 = await asyncio.gather(
            apply_migrations(c1, str(tmp_path)), apply_migrations(c2, str(tmp_path))
        )
        assert sorted(r1 + r2) == ["0001", "0002", "0003"]
        rows = await c1.fetch("SELECT version FROM schema_migrations ORDER BY version")
        assert [r["version"] for r in rows] == ["0001", "0002", "0003"]
        assert await pending_migrations(c1, str(tmp_path)) == []
        # The session lock is released afterwards (no leaked advisory locks).
        held = await c1.fetchval(
            "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND pid = pg_backend_pid()"
        )
        assert held == 0
    finally:
        await c1.close()
        await c2.close()


async def test_pending_migrations_reports_unapplied(scratch_schema, tmp_path) -> None:
    _write(tmp_path, {"0001_a.up.sql": "CREATE TABLE t_a (id int);"})
    c = await _connect(scratch_schema)
    try:
        assert await pending_migrations(c, str(tmp_path)) == ["0001"]
        await apply_migrations(c, str(tmp_path))
        _write(tmp_path, {"0002_b.up.sql": "CREATE TABLE t_b (id int);"})
        assert await pending_migrations(c, str(tmp_path)) == ["0002"]
    finally:
        await c.close()


def _cli(schema: str, migrations_dir: Path) -> subprocess.CompletedProcess:
    sep = "&" if "?" in settings.dsn else "?"
    env = {
        **os.environ,
        "DATABASE_URL": f"{settings.dsn}{sep}search_path={schema}",
        "MIGRATIONS_DIR": str(migrations_dir),
        "RAGGIE_ENV": "test",
    }
    return subprocess.run(
        [sys.executable, "-m", "raggie_control_plane.db.migrate"],
        cwd=_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


async def test_cli_applies_and_exits_zero(scratch_schema, tmp_path) -> None:
    _write(tmp_path, {"0001_a.up.sql": "CREATE TABLE t_a (id int);"})
    proc = await asyncio.to_thread(_cli, scratch_schema, tmp_path)
    assert proc.returncode == 0, proc.stderr
    c = await _connect(scratch_schema)
    try:
        assert await pending_migrations(c, str(tmp_path)) == []
    finally:
        await c.close()


async def test_cli_exits_nonzero_on_failure(scratch_schema, tmp_path) -> None:
    _write(tmp_path, {"0001_bad.up.sql": "CREATE TABLE broken ("})
    proc = await asyncio.to_thread(_cli, scratch_schema, tmp_path)
    assert proc.returncode != 0
    assert "0001" in proc.stderr


@pytest.mark.requires_postgres  # runs the app lifespan inline (no `client` fixture)
@pytest.mark.requires_redis
def test_readyz_fails_when_schema_is_behind(monkeypatch, tmp_path) -> None:
    with TestClient(app) as client:
        assert client.get("/readyz").status_code == 200
        # Bundle one migration the database has never seen.
        for f in Path(settings.migrations_dir).glob("*.up.sql"):
            (tmp_path / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
        _write(tmp_path, {"9999_future.up.sql": "SELECT 1;"})
        monkeypatch.setattr(settings, "migrations_dir", str(tmp_path))
        r = client.get("/readyz")
        assert r.status_code == 503 and "schema" in r.json()["status"]
