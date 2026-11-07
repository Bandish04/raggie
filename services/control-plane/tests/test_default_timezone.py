# SPDX-License-Identifier: Apache-2.0

"""New scheduled tasks and users default to a neutral timezone (UTC, or
DEFAULT_TIMEZONE), not a country-specific one. Existing rows keep theirs."""

from pathlib import Path

import pytest

from raggie_control_plane import config as config_module
from raggie_control_plane.api.scheduled_tasks import ScheduledTaskIn
from raggie_control_plane.config import (
    DEFAULT_TIMEZONE,
    InsecureConfigurationError,
    Settings,
    validate_runtime_secrets,
)
from raggie_control_plane.scheduling import effective_timezone

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


def test_default_is_utc() -> None:
    assert DEFAULT_TIMEZONE == "UTC"
    assert Settings(_env_file=None).default_timezone == "UTC"


def test_env_knob(monkeypatch) -> None:
    monkeypatch.setenv("DEFAULT_TIMEZONE", "Europe/Berlin")
    assert Settings(_env_file=None).default_timezone == "Europe/Berlin"


def test_invalid_default_timezone_refuses_to_boot() -> None:
    cfg = Settings(_env_file=None, raggie_env="development", default_timezone="Mars/Olympus")
    with pytest.raises(InsecureConfigurationError, match="DEFAULT_TIMEZONE"):
        validate_runtime_secrets(cfg)


def test_new_task_body_defaults_to_the_configured_zone(monkeypatch) -> None:
    body = {
        "name": "n",
        "workspace_id": "00000000-0000-0000-0000-000000000001",
        "prompt": "p",
        "cron": "0 9 * * *",
    }
    assert ScheduledTaskIn(**body).timezone == "UTC"
    monkeypatch.setattr(config_module.settings, "default_timezone", "Asia/Tokyo")
    assert ScheduledTaskIn(**body).timezone == "Asia/Tokyo"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("  Europe/Istanbul ", "Europe/Istanbul"),
        ("", "UTC"),
        ("   ", "UTC"),
        (None, "UTC"),
    ],
)
def test_blank_timezone_falls_back_to_the_default(value, expected) -> None:
    assert effective_timezone(value) == expected


def test_model_defaults_follow_the_setting(monkeypatch) -> None:
    from raggie_control_plane.models import ScheduledTask, User

    monkeypatch.setattr(config_module.settings, "default_timezone", "UTC")
    assert User.model_fields["timezone"].get_default(call_default_factory=True) == "UTC"
    assert ScheduledTask.model_fields["timezone"].get_default(call_default_factory=True) == "UTC"


def test_no_country_specific_default_left_in_code() -> None:
    src = Path(config_module.__file__).resolve().parent
    hits = [
        p.relative_to(src)
        for p in src.rglob("*.py")
        if "Europe/Istanbul" in p.read_text(encoding="utf-8") and p.name != "demo.py"
    ]
    assert hits == []


def test_0028_changes_only_column_defaults() -> None:
    up = (MIGRATIONS / "0028_neutral_defaults.up.sql").read_text(encoding="utf-8")
    down = (MIGRATIONS / "0028_neutral_defaults.down.sql").read_text(encoding="utf-8")
    for text in (up, down):
        assert text.startswith("-- SPDX-License-Identifier: Apache-2.0")
        assert "UPDATE " not in text.upper().replace("ON UPDATE", "")  # rows untouched
    assert "ALTER COLUMN timezone SET DEFAULT 'UTC'" in up
    assert up.count("SET DEFAULT 'UTC'") == 2  # users + scheduled_tasks
    assert down.count("SET DEFAULT 'Europe/Istanbul'") == 2


async def test_0028_new_rows_get_utc_and_existing_rows_keep_theirs(conn) -> None:
    """DB-backed (CI)."""
    up = (MIGRATIONS / "0028_neutral_defaults.up.sql").read_text(encoding="utf-8")
    down = (MIGRATIONS / "0028_neutral_defaults.down.sql").read_text(encoding="utf-8")
    await conn.execute(down)
    old = await conn.fetchval(
        "INSERT INTO users (email, password_hash) VALUES ('tz-old@x.test', 'x') RETURNING id"
    )
    await conn.execute(up)
    await conn.execute(up)  # idempotent
    new = await conn.fetchval(
        "INSERT INTO users (email, password_hash) VALUES ('tz-new@x.test', 'x') RETURNING id"
    )
    zones = dict(
        await conn.fetch("SELECT id, timezone FROM users WHERE id = ANY($1::uuid[])", [old, new])
    )
    assert zones == {old: "Europe/Istanbul", new: "UTC"}
    defaults = dict(
        await conn.fetch(
            "SELECT table_name, column_default FROM information_schema.columns"
            " WHERE table_schema = current_schema() AND column_name = 'timezone'"
            "   AND table_name IN ('users', 'scheduled_tasks')"
        )
    )
    assert all("'UTC'" in d for d in defaults.values()) and len(defaults) == 2
    await conn.execute(down)
    await conn.execute(down)  # idempotent
    await conn.execute(up)
