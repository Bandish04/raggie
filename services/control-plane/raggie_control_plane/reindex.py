# SPDX-License-Identifier: Apache-2.0
"""Re-publish every live document into the embeddings gateway's collection.

    python -m raggie_control_plane.reindex

For a restore without a vector backup (``scripts/restore.sh --reindex``): Qdrant
is empty, so every live document that still has its raw file is re-armed and
re-published, not only the ones on another fingerprint (that narrower job is
Admin → AI → Embeddings → Re-embed). The gateway's current profile is accepted
(audited like a re-embed, trigger ``cli``) and the bundled migrations run first,
exactly as on a control-plane boot.

Needs Postgres, Redis and the embeddings service. The ingestion workers do the
embedding once they run. Point ids are deterministic, so running it twice only
costs a second embedding pass.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

import asyncpg

from raggie_control_plane.db.repositories import AuditRepo, SettingsRepo, WorkspaceRepo
from raggie_control_plane.embeddings_profile import (
    AUDIT_REEMBED_STARTED,
    EmbeddingsProfile,
    GatewayUnavailableError,
    IngestTarget,
    ReembedBusyError,
    ReembedLease,
    reembed_lease,
    reindex_workspace,
)
from raggie_control_plane.infra.publisher import EventPublisher


class ReindexBusyError(RuntimeError):
    """A re-embed is already running (another replica or an admin request)."""


class ReindexConflictError(RuntimeError):
    """Another writer stored a different embedding profile while we ran."""


class ReindexPartialError(RuntimeError):
    """The run stopped part-way; ``result`` holds what was re-published."""

    def __init__(self, message: str, result: dict) -> None:
        super().__init__(message)
        self.result = result


async def reindex_all(
    conn: asyncpg.Connection, publisher: EventPublisher, profile: EmbeddingsProfile
) -> dict:
    """Accept the gateway's profile and re-publish every live document with a
    raw file. The re-embed lease is held from before the profile is stored to
    the end. Raises GatewayUnavailableError / ReindexBusyError /
    ReindexConflictError / ReindexPartialError (after auditing the partial run)."""
    info = await profile.client.get(force=True)
    try:
        async with reembed_lease(conn) as lease:
            return await _reindex_leased(conn, publisher, profile, info, lease)
    except ReembedBusyError as exc:  # acquiring; a lost lease mid-run is partial
        raise ReindexBusyError(str(exc)) from exc


async def _reindex_leased(
    conn: asyncpg.Connection,
    publisher: EventPublisher,
    profile: EmbeddingsProfile,
    info,
    lease: ReembedLease,
) -> dict:
    settings_repo = SettingsRepo(conn)
    stored, _ = await settings_repo.get_embedding_profile()
    if not await profile.store(conn, info, expected=stored, reason="restore_reindex"):
        # False is either "already this profile" or a lost compare-and-set.
        now, _ = await settings_repo.get_embedding_profile()
        if now != info.fingerprint:
            raise ReindexConflictError(
                f"the embedding profile changed to {now} while storing {info.fingerprint}"
            )
    target = IngestTarget.of(info)
    workspaces = await WorkspaceRepo(conn).list_all()
    reindexed = skipped = done = 0
    for ws in workspaces:
        try:
            await lease.keep_alive()
            res = await reindex_workspace(conn, publisher, ws, target, keep_alive=lease.keep_alive)
        except Exception as exc:  # audited below, then reported without a traceback
            partial = {
                "reindexed": reindexed,
                "skipped": skipped,
                "workspaces": len(workspaces),
                "workspaces_done": done,
                "failed_workspace": str(ws.id),
                "error": type(exc).__name__,
                "fingerprint": info.fingerprint,
                "collection": info.collection,
                "partial": True,
            }
            await AuditRepo(conn).record(
                AUDIT_REEMBED_STARTED,
                target=info.fingerprint,
                metadata={"trigger": "cli", **partial},
            )
            raise ReindexPartialError(
                f"stopped in workspace {ws.id} after {reindexed} document(s): {exc}", partial
            ) from exc
        reindexed += res["reindexed"]
        skipped += res["skipped"]
        done += 1
    result = {
        "reindexed": reindexed,
        "skipped": skipped,
        "workspaces": len(workspaces),
        "fingerprint": info.fingerprint,
        "collection": info.collection,
    }
    if reindexed:
        await AuditRepo(conn).record(
            AUDIT_REEMBED_STARTED,
            target=info.fingerprint,
            metadata={"trigger": "cli", **result},
        )
    return result


async def run(
    conn: asyncpg.Connection, publisher: EventPublisher, profile: EmbeddingsProfile
) -> int:
    """reindex_all for the CLI: the result on stdout, failures as one line on
    stderr (no traceback). 0 ok, 1 partial, 2 nothing done."""
    try:
        result = await reindex_all(conn, publisher, profile)
    except ReindexPartialError as exc:
        print(f"reindex: stopped: {exc}", file=sys.stderr)
        print(json.dumps(exc.result), file=sys.stderr)
        return 1
    except (GatewayUnavailableError, ReindexBusyError, ReindexConflictError) as exc:
        print(f"reindex: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result))
    return 0


async def _main() -> int:
    from raggie_control_plane.config import settings, validate_runtime_secrets
    from raggie_control_plane.db.migrate import apply_migrations
    from raggie_control_plane.db.pool import create_pool
    from raggie_control_plane.infra.publisher import RedisEventPublisher
    from raggie_control_plane.infra.redisconn import create_redis

    validate_runtime_secrets(settings)
    pool = await create_pool()
    redis_conn = create_redis(settings)
    try:
        async with pool.acquire() as conn:
            await apply_migrations(conn, settings.migrations_dir)
            return await run(
                conn,
                RedisEventPublisher(redis_conn.client),
                EmbeddingsProfile.from_settings(settings),
            )
    finally:
        await redis_conn.aclose()
        await pool.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m raggie_control_plane.reindex",
        description="Re-publish every live document into the embeddings gateway's "
        "collection (after a restore without a Qdrant backup).",
    )
    parser.parse_args(argv)
    return asyncio.run(_main())


if __name__ == "__main__":
    sys.exit(main())
