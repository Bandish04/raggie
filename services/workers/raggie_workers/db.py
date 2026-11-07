# SPDX-License-Identifier: Apache-2.0

"""asyncpg pool for document-status writes (PgBouncer-compatible)."""

from __future__ import annotations

import asyncpg

from raggie_workers.config import settings


async def create_pool(dsn: str | None = None) -> asyncpg.Pool:
    return await asyncpg.create_pool(
        dsn=dsn or settings.dsn,
        min_size=1,
        max_size=5,
        statement_cache_size=0,  # PgBouncer transaction-mode safe
    )
