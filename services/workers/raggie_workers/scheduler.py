# SPDX-License-Identifier: Apache-2.0

"""Scheduler worker: run due scheduled tasks and the document sweeps.

A scheduled task is a prompt the assistant runs on a cron schedule for its owner
(table ``scheduled_tasks``, migration 0014). This worker polls enabled tasks by
``next_run_at`` every ``SCHEDULER_POLL_SECONDS``, executes each one headlessly via
the edge's internal run-task endpoint, writes the result into the ``notifications``
inbox, and records the run's outcome on the task.

Double-run / re-pick safety (the core correctness concern):
  Claiming and executing are SEPARATE phases.
    1. CLAIM (short transaction): SELECT due tasks ``FOR UPDATE SKIP LOCKED`` so two
       scheduler replicas can never grab the same row; for each, IMMEDIATELY advance
       ``next_run_at`` to the next cron occurrence and stamp ``last_run_at = now()``,
       then COMMIT (releasing the locks). After the commit the task's next fire is in
       the future, so a slow execution can't be re-picked on the next poll.
    2. RUN (outside any lock): POST to the edge, then store the notification and the
       ``last_status``. A long-running execution holds no DB lock and blocks nothing.

The next occurrence is computed with croniter + zoneinfo honoring the task's own
timezone (DST-correct), anchored at now, and returned as a UTC-aware datetime so it
compares correctly against ``now()`` (timestamptz) on the next poll.

Robustness: one task failing (edge error, network, bad cron) must neither kill the
loop nor block the other claimed tasks — each is isolated and logged with its id.

The same process runs the document sweeps (retry FAILED, re-publish stale
PENDING); see "Document sweeps" below.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import asyncpg
import httpx
from croniter import croniter
from prometheus_client import Counter

from raggie_workers.bus import RedisStreamsBus
from raggie_workers.config import settings
from raggie_workers.redisconn import create_redis

log = logging.getLogger("scheduler")

# How many due tasks to claim per poll. A small batch keeps each claim transaction
# short and bounds how long any one poll's run phase takes.
_CLAIM_LIMIT = 20


def _next_run_at(cron: str, timezone: str, *, after: datetime | None = None) -> datetime:
    """Next cron occurrence strictly after ``after`` (default now), as a UTC-aware
    datetime. The cron is interpreted in the task's local timezone so wall-clock
    schedules stay correct across DST transitions; the result is converted to UTC for
    storage/comparison against ``now()``.

    A missing or unknown timezone falls back to DEFAULT_TIMEZONE (same setting as
    the control-plane) rather than failing the claim; the API validated it already."""
    default = settings.default_timezone
    try:
        tz = ZoneInfo(timezone or default)
    except (ZoneInfoNotFoundError, ValueError):
        log.warning("scheduler unknown timezone %r; using %s", timezone, default)
        tz = ZoneInfo(default)
    base = (after or datetime.now(UTC)).astimezone(tz)
    nxt = croniter(cron, base).get_next(datetime)  # tz-aware (carries `base`'s tzinfo)
    return nxt.astimezone(UTC)


async def _claim_due_tasks(pool: asyncpg.Pool) -> list[asyncpg.Record]:
    """Atomically claim up to ``_CLAIM_LIMIT`` due tasks and advance their schedule.

    Runs in one short transaction: lock the due rows (SKIP LOCKED so concurrent
    schedulers don't collide), then for each row push ``next_run_at`` to the next
    occurrence and set ``last_run_at = now()``. Returns the CLAIMED rows (their
    pre-advance snapshot) for the run phase. The lock is released on commit, so the
    subsequent (possibly slow) execution holds nothing."""
    claimed: list[asyncpg.Record] = []
    async with pool.acquire() as conn:
        async with conn.transaction():
            # The owner's language comes with the claim (no extra round trip);
            # OF t: lock only the task rows, never the joined users rows.
            rows = await conn.fetch(
                """
                SELECT t.id, t.org_id, t.user_id, t.workspace_id, t.name, t.prompt,
                       t.cron, t.timezone, t.web_search, t.deep_search, t.model,
                       t.answer_style, u.locale AS owner_locale
                  FROM scheduled_tasks t
                  LEFT JOIN users u ON u.id = t.user_id
                 WHERE t.enabled AND t.next_run_at IS NOT NULL AND t.next_run_at <= now()
                 ORDER BY t.next_run_at
                 LIMIT $1
                 FOR UPDATE OF t SKIP LOCKED
                """,
                _CLAIM_LIMIT,
            )
            for row in rows:
                try:
                    nxt = _next_run_at(row["cron"], row["timezone"])
                except Exception:  # noqa: BLE001 — a bad cron must not abort the whole claim
                    # Disable the task so it stops re-firing every poll; surface why.
                    log.exception("scheduler invalid cron for task %s; disabling", row["id"])
                    await conn.execute(
                        "UPDATE scheduled_tasks"
                        " SET enabled = false, last_status = 'error', last_run_at = now()"
                        " WHERE id = $1",
                        row["id"],
                    )
                    continue
                await conn.execute(
                    "UPDATE scheduled_tasks SET next_run_at = $2, last_run_at = now()"
                    " WHERE id = $1",
                    row["id"],
                    nxt,
                )
                claimed.append(row)
    return claimed


# Notification text for a failed run, per owner language. The edge's own
# {"message"} is already localized (from Accept-Language) and passes through.
_MESSAGES = {
    "en": {
        "failed": "The task could not run: {reason}",
        "no_answer": "no answer was returned",
        "timeout": "the request timed out",
        "connection": "connection error ({name})",
        "unexpected": "unexpected error ({name})",
    },
    "tr": {
        "failed": "Görev çalıştırılamadı: {reason}",
        "no_answer": "yanıt alınamadı",
        "timeout": "zaman aşımına uğradı",
        "connection": "bağlantı hatası ({name})",
        "unexpected": "beklenmeyen hata ({name})",
    },
}


def _task_locale(task) -> str:
    """The task owner's language (users.locale), else the install default."""
    owner = str(task.get("owner_locale") or "").strip().lower()
    return owner if owner in _MESSAGES else settings.install_locale


def _failure_body(locale: str, reason: str) -> str:
    reason = reason.strip()
    if not reason.endswith((".", "!", "?")):
        reason += "."
    return _MESSAGES[locale]["failed"].format(reason=reason)


def _message(locale: str, key: str, **values: str) -> str:
    return _MESSAGES[locale][key].format(**values)


async def _execute_task(
    client: httpx.AsyncClient, pool: asyncpg.Pool, task: asyncpg.Record
) -> None:
    """Run one already-claimed task: call the edge, store the notification + status.

    Never raises: any failure is turned into an 'error' notification + status so the
    user still sees that the run happened, and the loop keeps going."""
    task_id = task["id"]
    locale = _task_locale(task)
    answer: str | None = None
    status = "error"
    try:
        resp = await client.post(
            f"{settings.edge_url}/api/v1/internal/run-task",
            # Accept-Language: the edge localizes its error messages from it.
            headers={"X-Internal-Secret": settings.internal_api_secret, "Accept-Language": locale},
            json={
                "workspace_id": str(task["workspace_id"]),
                "user_id": str(task["user_id"]),
                "prompt": task["prompt"],
                "web_search": task["web_search"],
                "deep_search": task["deep_search"],
                # model/answer_style are nullable in the DB; the edge treats "" as
                # "use the default", so coalesce None -> "".
                "model": task["model"] or "",
                "answer_style": task["answer_style"] or "",
            },
            # SCHEDULER_TASK_TIMEOUT_SECONDS: generous, since a deep-research run
            # is slow. The edge sheds (503) rather than hanging.
            timeout=settings.scheduler_task_timeout_seconds,
        )
        if resp.status_code == 200:
            answer = str(resp.json().get("answer", "")).strip()
            if answer:
                status = "ok"
            else:
                answer = None  # empty answer => treat as error below
                body = _failure_body(locale, _message(locale, "no_answer"))
        if resp.status_code != 200:
            # The edge returns {"error","message"} localized for Accept-Language;
            # fall back to the status code when the body isn't the expected shape.
            reason = f"HTTP {resp.status_code}"
            try:
                payload = resp.json()
                if isinstance(payload, dict) and payload.get("message"):
                    reason = str(payload["message"])
            except (ValueError, httpx.HTTPError):
                pass
            body = _failure_body(locale, reason)
    except httpx.TimeoutException:
        body = _failure_body(locale, _message(locale, "timeout"))
    except httpx.HTTPError as exc:
        body = _failure_body(locale, _message(locale, "connection", name=type(exc).__name__))
    except Exception as exc:  # noqa: BLE001 — defensive: nothing here may crash the loop
        log.exception("scheduler unexpected error running task %s", task_id)
        body = _failure_body(locale, _message(locale, "unexpected", name=type(exc).__name__))

    final_body = answer if status == "ok" else body
    try:
        await _persist_result(pool, task, status=status, body=final_body)
    except Exception:  # noqa: BLE001 — a DB write failure must not kill the loop
        log.exception("scheduler failed to persist result for task %s", task_id)
        return
    log.info("scheduler ran task %s status=%s", task_id, status)


async def _persist_result(
    pool: asyncpg.Pool, task: asyncpg.Record, *, status: str, body: str
) -> None:
    """Insert the notification and record last_status. next_run_at/last_run_at were
    already advanced at claim time, so we only touch last_status here."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "INSERT INTO notifications"
                " (org_id, user_id, task_id, kind, title, body, is_read)"
                " VALUES ($1, $2, $3, 'task_result', $4, $5, false)",
                task["org_id"],
                task["user_id"],
                task["id"],
                task["name"],
                body,
            )
            await conn.execute(
                "UPDATE scheduled_tasks SET last_status = $2 WHERE id = $1",
                task["id"],
                status,
            )


# ─────────────────────────── Document sweeps ────────────────────────────────
# The ingestion worker is stateless: on error it marks the doc FAILED and acks.
# The sweeps below re-publish raggie.document.uploaded (same payload as the
# upload path) for retryable FAILED docs and for docs stuck in PENDING. Retry
# state lives only in Postgres. Point ids are uuid5(document_id, chunk index),
# so a re-ingest overwrites instead of duplicating.

# raggie.document.uploaded topic name (mirrors the publisher / contracts/events.md).
_DOCUMENT_UPLOADED = "raggie.document.uploaded"

# Recover the embedding dim from raggie_chunks_d{dim} (legacy) or
# raggie_chunks_d{dim}_{fingerprint} (gateway profiles).
_COLLECTION_DIM = re.compile(r"_d(\d+)(?:_[0-9a-f]{8})?$")


def _dim_from_collection(collection: str) -> int | None:
    m = _COLLECTION_DIM.search(collection or "")
    return int(m.group(1)) if m else None


async def _sweep_failed_documents(pool: asyncpg.Pool, bus: RedisStreamsBus) -> int:
    """Re-arm and re-publish retryable FAILED documents; returns the count.

    Selects live docs (never deleted/archived: re-ingesting would restore erased
    chunks) with retry_count < max_retries whose backoff (1 min * 2^retry_count,
    capped) has elapsed, and flips them to PENDING with retry_count++ in one
    statement (FOR UPDATE SKIP LOCKED: concurrent sweeps never double-claim).
    Once retry_count reaches max_retries a doc stays FAILED for good, which stops
    corrupt files from looping. Publishing happens after the commit; if it fails,
    the doc stays PENDING and the stale-PENDING sweep picks it up later."""
    cap = max(0, settings.retry_backoff_cap_seconds)
    rows = await pool.fetch(
        """
        UPDATE documents
           SET status = 'PENDING',
               retry_count = retry_count + 1,
               last_retry_at = now()
         WHERE id IN (
             SELECT id FROM documents
              WHERE status = 'FAILED'
                AND deleted_at IS NULL
                AND archived_at IS NULL
                AND retry_count < max_retries
                AND object_key IS NOT NULL
                AND (
                    last_retry_at IS NULL
                    OR last_retry_at < now() - LEAST(
                        interval '1 minute' * power(2, retry_count),
                        make_interval(secs => $1)
                    )
                )
              ORDER BY last_retry_at NULLS FIRST
              LIMIT $2
              FOR UPDATE SKIP LOCKED
         )
        RETURNING id, workspace_id, filename, object_key,
                  qdrant_collection_name, retry_count, max_retries,
                  -- tolerant of a DB without migration 0026 (rolling deploy)
                  to_jsonb(documents.*) ->> 'embedding_fingerprint' AS embedding_fingerprint
        """,
        cap,
        max(1, settings.retry_sweep_batch),
    )
    if not rows:
        return 0

    retried = 0
    for row in rows:
        dim = _dim_from_collection(row["qdrant_collection_name"])
        if dim is None:
            # Cannot reconstruct the embedding dim → cannot re-ingest deterministically.
            log.warning(
                "retry-sweep: document %s has unparseable collection %r; skipping",
                row["id"],
                row["qdrant_collection_name"],
            )
            continue
        await bus.publish(_DOCUMENT_UPLOADED, _upload_payload(row, dim))
        log.info(
            "retry-sweep re-enqueued document %s (attempt %s/%s)",
            row["id"],
            row["retry_count"],  # post-increment: this is the attempt number now in flight
            row["max_retries"],
        )
        retried += 1
    return retried


STALE_REPUBLISHED = Counter(
    "raggie_workers_stale_pending_republished_total",
    "PENDING/PROCESSING documents re-published by the stale-PENDING sweep.",
)


async def _sweep_stale_pending(
    pool: asyncpg.Pool, bus: RedisStreamsBus, *, stale_seconds: int, batch: int
) -> int:
    """Re-publish live documents stuck in PENDING/PROCESSING; returns the count.

    Redis/Valkey replication is asynchronous, so an upload event can be lost in
    a failover; a worker that crashes mid-document stops heartbeating its
    PROCESSING row. Either way updated_at stops moving. Docs older than
    stale_seconds are claimed (FOR UPDATE SKIP LOCKED, at most `batch`) and set
    to PENDING; the set_updated_at trigger then restarts their window, so they
    are not picked again next tick. A duplicate delivery only costs work."""
    rows = await pool.fetch(
        """
        UPDATE documents
           SET status = 'PENDING'
         WHERE id IN (
             SELECT id FROM documents
              WHERE status IN ('PENDING', 'PROCESSING')
                AND deleted_at IS NULL
                AND archived_at IS NULL
                AND object_key IS NOT NULL
                AND updated_at < now() - make_interval(secs => $1)
              ORDER BY updated_at
              LIMIT $2
              FOR UPDATE SKIP LOCKED
         )
        RETURNING id, workspace_id, filename, object_key, qdrant_collection_name,
                  -- tolerant of a DB without migration 0026 (rolling deploy)
                  to_jsonb(documents.*) ->> 'embedding_fingerprint' AS embedding_fingerprint
        """,
        stale_seconds,
        batch,
    )
    republished = 0
    for row in rows:
        dim = _dim_from_collection(row["qdrant_collection_name"])
        if dim is None:
            log.warning(
                "stale-pending sweep: document %s has unparseable collection %r; skipping",
                row["id"],
                row["qdrant_collection_name"],
            )
            continue
        await bus.publish(_DOCUMENT_UPLOADED, _upload_payload(row, dim))
        log.warning("stale-pending sweep re-published document %s", row["id"])
        STALE_REPUBLISHED.inc()
        republished += 1
    return republished


def _upload_payload(row: asyncpg.Record, dim: int) -> dict:
    """document.uploaded payload with the same fields the control-plane emits, so
    a re-published doc lands in its profile's collection and is checked against
    the profile it was indexed for."""
    return {
        "document_id": str(row["id"]),
        "workspace_id": str(row["workspace_id"]),
        "filename": row["filename"],
        "object_key": row["object_key"],
        "embedding_dim": dim,
        "collection": row["qdrant_collection_name"],
        "embedding_fingerprint": row["embedding_fingerprint"],
    }


async def run_retry_sweep(pool: asyncpg.Pool, bus: RedisStreamsBus) -> None:
    """Every retry_sweep_seconds run both document sweeps (FAILED retries, stale
    PENDING). A transient DB or Redis error is logged and retried next tick."""
    interval = max(1, settings.retry_sweep_seconds)
    log.info("retry sweep ready", extra={"interval_seconds": interval})
    while True:
        try:
            n = await _sweep_failed_documents(pool, bus)
            if n:
                log.info("retry sweep re-enqueued %s document(s)", n)
            stale = await _sweep_stale_pending(
                pool,
                bus,
                stale_seconds=settings.stale_pending_seconds,
                batch=settings.stale_pending_batch,
            )
            if stale:
                log.warning("stale-pending sweep re-published %s document(s)", stale)
        except Exception:  # noqa: BLE001 — a transient error must not kill the loop
            log.exception("retry sweep failed; retrying next tick")
        await asyncio.sleep(interval)


async def _run_task_loop(pool: asyncpg.Pool) -> None:
    """Poll loop: every SCHEDULER_POLL_SECONDS, claim due tasks then execute them.

    The claim phase is atomic and advances each task's schedule before release, so a
    slow execution is never re-picked and concurrent schedulers never double-run a
    task. Execution is isolated per task. Stops cleanly when cancelled (shutdown)."""
    if not settings.internal_api_secret:
        # Without the shared secret the edge endpoint is dormant and every run would
        # 401/503. Idle loudly rather than hammering the edge with doomed requests.
        # (The retry sweep runs independently — it doesn't touch the edge.)
        log.warning(
            "scheduler: INTERNAL_API_SECRET is empty; the run-task endpoint is "
            "disabled. Idling task execution — set INTERNAL_API_SECRET to enable "
            "scheduled tasks. The document retry sweep still runs."
        )
        while True:
            await asyncio.sleep(settings.scheduler_poll_seconds)

    poll = max(1, settings.scheduler_poll_seconds)
    log.info("scheduler worker ready", extra={"poll_seconds": poll, "edge_url": settings.edge_url})
    # Each run-task POST sets its own (long) timeout; the client default bounds
    # anything else so no call can hang the loop forever.
    async with httpx.AsyncClient(timeout=settings.scheduler_task_timeout_seconds) as client:
        while True:
            try:
                claimed = await _claim_due_tasks(pool)
            except Exception:  # noqa: BLE001 — a transient DB error must not kill the loop
                log.exception("scheduler claim failed; retrying next poll")
                claimed = []
            for task in claimed:
                # Sequential execution: the edge sheds (503) when its outbound pool is
                # busy, and tasks are not latency-critical — keep load predictable.
                await _execute_task(client, pool, task)
            await asyncio.sleep(poll)


async def run_scheduler(pool: asyncpg.Pool) -> None:
    """Run the scheduled-task loop and the document sweeps concurrently.

    The task loop calls the edge (and idles without INTERNAL_API_SECRET); the
    sweeps only re-publish events. If either loop ever raises, the gather lets
    the process exit so the orchestrator restarts it."""
    redis = create_redis(settings).client  # Sentinel-aware, like every worker client
    bus = RedisStreamsBus(redis)
    try:
        await asyncio.gather(
            _run_task_loop(pool),
            run_retry_sweep(pool, bus),
        )
    finally:
        await redis.aclose()
