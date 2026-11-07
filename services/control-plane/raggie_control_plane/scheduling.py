# SPDX-License-Identifier: Apache-2.0

"""Cron schedule helpers for scheduled tasks (0014).

The control plane validates a task's schedule and computes when it should next
fire; the separate scheduler WORKER polls ``scheduled_tasks.next_run_at`` and
executes due tasks. Keeping the computation here (not in the worker) means the
stored ``next_run_at`` is always consistent with what the user just saved.

A schedule is a standard 5-field cron expression evaluated in an IANA timezone.
The returned instant is UTC-aware so it can be stored verbatim in a TIMESTAMPTZ
and compared against ``now()`` regardless of the worker's local timezone.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter


def effective_timezone(value: str | None) -> str:
    """A user-supplied timezone, or DEFAULT_TIMEZONE when it is blank."""
    from raggie_control_plane.config import settings

    return (value or "").strip() or settings.default_timezone


class InvalidSchedule(ValueError):
    """A cron expression or timezone the user supplied is not valid. The API
    layer maps this to a 400."""


def _resolve_tz(tz: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError, KeyError) as exc:
        raise InvalidSchedule(f"unknown timezone: {tz!r}") from exc


def validate_cron(cron: str) -> str:
    """Return a trimmed, validated 5-field cron expression or raise
    ``InvalidSchedule``. croniter also accepts 6-field (seconds) and named
    expressions; we deliberately require exactly the standard 5 fields so the
    stored schedule is unambiguous for the worker."""
    cleaned = cron.strip()
    if len(cleaned.split()) != 5 or not croniter.is_valid(cleaned):
        raise InvalidSchedule("cron must be a standard 5-field expression (min hour dom mon dow)")
    return cleaned


def next_run(cron: str, tz: str, after: datetime | None = None) -> datetime:
    """Compute the next fire time for ``cron`` in timezone ``tz``, strictly after
    ``after`` (defaults to now). Returns a UTC-aware datetime.

    Raises ``InvalidSchedule`` if the cron expression or timezone is invalid.
    """
    cleaned = validate_cron(cron)
    zone = _resolve_tz(tz)
    # Anchor the iterator in the task's local zone so DST-sensitive fields (e.g.
    # "every day at 08:00") resolve to the intended local wall-clock time.
    base = (after or datetime.now(UTC)).astimezone(zone)
    upcoming = croniter(cleaned, base).get_next(datetime)
    return upcoming.astimezone(UTC)
