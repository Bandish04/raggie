# SPDX-License-Identifier: Apache-2.0

"""compose_sql: the one place SQL text is assembled from identifier fragments."""

import pytest

from raggie_control_plane.db.repositories import compose_sql


def test_composes_allow_listed_fragments() -> None:
    sql = compose_sql(
        "UPDATE users SET {sets}, updated_at = now() WHERE id = $1",
        sets=["full_name = $2", "locale = $3", "chat_allowed_models = $4::jsonb"],
    )
    assert sql == (
        "UPDATE users SET full_name = $2, locale = $3, chat_allowed_models = $4::jsonb,"
        " updated_at = now() WHERE id = $1"
    )
    assert compose_sql("INSERT INTO t ({cols}) VALUES ({ph})", cols=["a", "b"], ph=["$1", "$2"])


@pytest.mark.parametrize(
    "fragment",
    [
        "name = $2; DROP TABLE users",
        "name = 'x'",
        "1=1 OR",
        "role = $2 --",
        "Name = $2",
        "",
        "a b",
        "$1); DELETE FROM users; --",
    ],
)
def test_rejects_anything_but_identifiers_and_placeholders(fragment) -> None:
    with pytest.raises(ValueError):
        compose_sql("UPDATE t SET {sets} WHERE id = $1", sets=[fragment])


def test_rejects_unknown_or_missing_slots() -> None:
    with pytest.raises((KeyError, ValueError)):
        compose_sql("SELECT {cols} FROM t", other=["a"])
