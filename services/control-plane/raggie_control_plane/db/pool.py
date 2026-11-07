# SPDX-License-Identifier: Apache-2.0

"""asyncpg connection pool factory.

The pool is configured for compatibility with PgBouncer **transaction** pooling:
server-side prepared statements are disabled
(``statement_cache_size=0``), and JSON/JSONB values are decoded to Python objects.
"""

from __future__ import annotations

import json

import asyncpg

from raggie_control_plane.config import settings


async def _init_connection(conn: asyncpg.Connection) -> None:
    # Decode json/jsonb to Python objects instead of raw strings.
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")
    await conn.set_type_codec("json", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


async def create_pool(dsn: str | None = None) -> asyncpg.Pool:
    return await asyncpg.create_pool(
        dsn=dsn or settings.dsn,
        min_size=settings.db_pool_min_size,
        max_size=settings.db_pool_max_size,
        statement_cache_size=0,  # REQUIRED for PgBouncer transaction mode
        init=_init_connection,
    )
