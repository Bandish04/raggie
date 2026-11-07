# SPDX-License-Identifier: Apache-2.0

"""Forward-only SQL migration runner.

The canonical DDL lives as golang-migrate-format files in ``migrations/``
(``NNNN_name.up.sql`` / ``.down.sql``). This applies pending ``*.up.sql`` files
in version order, each in its own transaction, recording them in
``schema_migrations``. Keeping raw SQL as the sole DDL source lets the Go edge's
sqlc read the exact same files (no second migration DSL).

Safe with several control-plane replicas booting at once: the whole run holds
a session-level advisory lock, and each file re-checks ``schema_migrations``
inside its own transaction, so every migration is applied exactly once.

Also a CLI for a k8s Job / ``make migrate``::

    python -m raggie_control_plane.db.migrate   # exit code != 0 on failure
"""

from __future__ import annotations

import asyncio
import logging
import re
import sys
from pathlib import Path

import asyncpg

log = logging.getLogger("migrate")

_UP_RE = re.compile(r"^(\d+)_.*\.up\.sql$")

# Advisory-lock key serializing migration runs across replicas / Jobs.
MIGRATION_LOCK_KEY = 0x5241474749450002  # "RAGGIE" + 2


def _version(path: Path) -> int:
    m = _UP_RE.match(path.name)
    if not m:
        raise ValueError(f"migration file does not match NNNN_name.up.sql: {path.name}")
    return int(m.group(1))


async def apply_migrations(conn: asyncpg.Connection, migrations_dir: str) -> list[str]:
    """Apply all pending up-migrations. Returns the versions newly applied."""
    files = sorted(Path(migrations_dir).glob("*.up.sql"), key=_version)
    await conn.execute("SELECT pg_advisory_lock($1)", MIGRATION_LOCK_KEY)
    try:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "  version TEXT PRIMARY KEY,"
            "  applied_at TIMESTAMPTZ NOT NULL DEFAULT now()"
            ")"
        )
        newly: list[str] = []
        for path in files:
            version = f"{_version(path):04d}"
            sql = path.read_text(encoding="utf-8")
            async with conn.transaction():
                # Re-checked inside the transaction (and under the same key as a
                # transaction lock): stays exactly-once even if the session lock
                # is not honoured, e.g. behind a transaction-pooling PgBouncer.
                await conn.execute("SELECT pg_advisory_xact_lock($1)", MIGRATION_LOCK_KEY)
                if await conn.fetchval(
                    "SELECT 1 FROM schema_migrations WHERE version = $1", version
                ):
                    continue
                try:
                    await conn.execute(sql)
                except Exception as exc:
                    raise MigrationError(
                        f"migration {version} ({path.name}) failed: {exc}"
                    ) from exc
                await conn.execute("INSERT INTO schema_migrations(version) VALUES($1)", version)
            log.info("applied migration %s (%s)", version, path.name)
            newly.append(version)
        return newly
    finally:
        await conn.execute("SELECT pg_advisory_unlock($1)", MIGRATION_LOCK_KEY)


class MigrationError(RuntimeError):
    """A migration file failed; the message names the version and file."""


async def pending_migrations(conn: asyncpg.Connection, migrations_dir: str) -> list[str]:
    """Bundled versions the database has not applied yet (readiness gate)."""
    exists = await conn.fetchval("SELECT to_regclass('schema_migrations') IS NOT NULL")
    applied = (
        {r["version"] for r in await conn.fetch("SELECT version FROM schema_migrations")}
        if exists
        else set()
    )
    bundled = [f"{_version(p):04d}" for p in Path(migrations_dir).glob("*.up.sql")]
    return sorted(v for v in bundled if v not in applied)


async def _cli() -> int:
    # Imported here so the module stays importable without full settings.
    from raggie_control_plane.config import settings

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        conn = await asyncpg.connect(settings.dsn)
    except Exception as exc:  # noqa: BLE001 — any connect failure is a failed run
        print(f"migrate: cannot connect to the database: {exc}", file=sys.stderr)
        return 2
    try:
        applied = await apply_migrations(conn, settings.migrations_dir)
    except Exception as exc:  # noqa: BLE001 — report and fail the Job
        print(f"migrate: {exc}", file=sys.stderr)
        return 1
    finally:
        await conn.close()
    suffix = f": {', '.join(applied)}" if applied else ""
    print(f"migrate: applied {len(applied)} migration(s){suffix}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_cli()))
