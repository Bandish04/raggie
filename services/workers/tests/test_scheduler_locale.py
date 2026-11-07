# SPDX-License-Identifier: Apache-2.0

"""Scheduled-task notifications follow the task owner's language (users.locale),
and the edge is told that language so its own messages match."""

import uuid

import httpx
import pytest

import raggie_workers.scheduler as scheduler
from raggie_workers.config import Settings


def _task(locale: str | None) -> dict:
    return {
        "id": uuid.uuid4(),
        "org_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "workspace_id": uuid.uuid4(),
        "name": "daily digest",
        "prompt": "summarize",
        "web_search": False,
        "deep_search": False,
        "model": None,
        "answer_style": None,
        "owner_locale": locale,
    }


class _Client:
    def __init__(self, outcome) -> None:
        self.outcome = outcome
        self.headers: list[dict] = []

    async def post(self, *_args, headers, timeout, **_kwargs):
        self.headers.append(headers)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


@pytest.fixture
def results(monkeypatch) -> list[dict]:
    captured: list[dict] = []

    async def persist(_pool, _task, *, status, body):
        captured.append({"status": status, "body": body})

    monkeypatch.setattr(scheduler, "_persist_result", persist)
    return captured


EDGE_TR = "Yapay zeka servisine şu anda ulaşılamıyor."
CASES = [
    (
        "ok",
        httpx.Response(200, json={"answer": "Daily summary."}),
        {"en": "Daily summary.", "tr": "Daily summary."},
        "ok",
    ),
    (
        "empty",
        httpx.Response(200, json={"answer": "  "}),
        {
            "en": "The task could not run: no answer was returned.",
            "tr": "Görev çalıştırılamadı: yanıt alınamadı.",
        },
        "error",
    ),
    (
        "edge-message",
        httpx.Response(502, json={"error": "upstream", "message": EDGE_TR}),
        {"en": f"The task could not run: {EDGE_TR}", "tr": f"Görev çalıştırılamadı: {EDGE_TR}"},
        "error",
    ),
    (
        "bare-status",
        httpx.Response(503, text="busy"),
        {"en": "The task could not run: HTTP 503.", "tr": "Görev çalıştırılamadı: HTTP 503."},
        "error",
    ),
    (
        "timeout",
        httpx.ReadTimeout("slow edge"),
        {
            "en": "The task could not run: the request timed out.",
            "tr": "Görev çalıştırılamadı: zaman aşımına uğradı.",
        },
        "error",
    ),
    (
        "connect",
        httpx.ConnectError("refused"),
        {
            "en": "The task could not run: connection error (ConnectError).",
            "tr": "Görev çalıştırılamadı: bağlantı hatası (ConnectError).",
        },
        "error",
    ),
    (
        "unexpected",
        RuntimeError("boom"),
        {
            "en": "The task could not run: unexpected error (RuntimeError).",
            "tr": "Görev çalıştırılamadı: beklenmeyen hata (RuntimeError).",
        },
        "error",
    ),
]


@pytest.mark.parametrize("locale", ["en", "tr"])
@pytest.mark.parametrize(
    ("case", "outcome", "expected", "status"), CASES, ids=[c[0] for c in CASES]
)
async def test_notification_language_and_accept_language(
    results, locale, case, outcome, expected, status
) -> None:
    client = _Client(outcome)
    await scheduler._execute_task(client, None, _task(locale))
    assert results == [{"status": status, "body": expected[locale]}]
    assert client.headers[0]["Accept-Language"] == locale


def test_edge_message_passes_through_untranslated() -> None:
    # The edge already localizes its message: the scheduler only adds its prefix.
    assert scheduler._failure_body("en", EDGE_TR) == f"The task could not run: {EDGE_TR}"


@pytest.mark.parametrize(
    ("owner", "default_locale", "next_public", "expected"),
    [
        ("tr", "en", "", "tr"),  # the owner's stored preference wins
        ("EN", "tr", "", "en"),  # normalized
        (None, "tr", "", "tr"),  # no owner row: DEFAULT_LOCALE
        (None, "", "tr", "tr"),  # then the web's NEXT_PUBLIC_DEFAULT_LOCALE
        (None, "", "", "en"),  # then English
        ("de", "", "", "en"),  # unsupported values never leak through
        (None, "fr", "", "en"),
    ],
)
def test_owner_locale_resolution(monkeypatch, owner, default_locale, next_public, expected) -> None:
    cfg = Settings(
        _env_file=None, default_locale=default_locale, next_public_default_locale=next_public
    )
    monkeypatch.setattr(scheduler, "settings", cfg)
    assert scheduler._task_locale({"owner_locale": owner}) == expected


def test_install_locale_env(monkeypatch) -> None:
    monkeypatch.setenv("DEFAULT_LOCALE", "tr")
    assert Settings(_env_file=None).install_locale == "tr"
    monkeypatch.setenv("DEFAULT_LOCALE", "")
    monkeypatch.setenv("NEXT_PUBLIC_DEFAULT_LOCALE", "tr")
    assert Settings(_env_file=None).install_locale == "tr"


def test_claim_query_reads_the_owner_locale_without_locking_users() -> None:
    import inspect

    src = inspect.getsource(scheduler._claim_due_tasks)
    assert "LEFT JOIN users" in src and "owner_locale" in src
    assert "FOR UPDATE OF t SKIP LOCKED" in src


async def test_claimed_rows_carry_owner_locale(pg_pool) -> None:
    """DB-backed (CI): the claim join returns users.locale as owner_locale."""
    org_id, ws_id, user_id, task_id = (str(uuid.uuid4()) for _ in range(4))
    async with pg_pool.acquire() as c:
        await c.execute("INSERT INTO organizations(id, name) VALUES($1::uuid, 'A')", org_id)
        await c.execute(
            "INSERT INTO workspaces(id, org_id, name, type)"
            " VALUES($1::uuid, $2::uuid, 'W', 'INTERNAL')",
            ws_id,
            org_id,
        )
        await c.execute(
            "INSERT INTO users(id, org_id, email, password_hash, role, locale)"
            " VALUES($1::uuid, $2::uuid, $3, 'x', 'STAFF', 'tr')",
            user_id,
            org_id,
            f"{user_id}@x.test",
        )
        await c.execute(
            "INSERT INTO scheduled_tasks(id, org_id, user_id, workspace_id, name, prompt,"
            " cron, timezone, enabled, next_run_at)"
            " VALUES($1::uuid, $2::uuid, $3::uuid, $4::uuid, 't', 'p', '0 9 * * *',"
            " 'UTC', true, now() - interval '1 minute')",
            task_id,
            org_id,
            user_id,
            ws_id,
        )
    rows = await scheduler._claim_due_tasks(pg_pool)
    mine = [r for r in rows if str(r["id"]) == task_id]
    assert mine and mine[0]["owner_locale"] == "tr"


def test_invalid_task_timezone_falls_back_to_default_timezone(monkeypatch) -> None:
    from datetime import UTC, datetime

    cfg = Settings(_env_file=None)
    assert cfg.default_timezone == "UTC"
    monkeypatch.setattr(scheduler, "settings", cfg)
    base = datetime(2026, 1, 1, 8, 30, tzinfo=UTC)
    # "0 9 * * *" evaluated in UTC (the default), not Europe/Istanbul (06:00 UTC).
    assert scheduler._next_run_at("0 9 * * *", "Not/AZone", after=base) == datetime(
        2026, 1, 1, 9, 0, tzinfo=UTC
    )
    monkeypatch.setattr(
        scheduler, "settings", Settings(_env_file=None, default_timezone="Asia/Tokyo")
    )
    assert scheduler._next_run_at("0 9 * * *", "", after=base) == datetime(
        2026, 1, 2, 0, 0, tzinfo=UTC
    )
    assert "Europe/Istanbul" not in open(scheduler.__file__, encoding="utf-8").read()
