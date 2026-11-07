# SPDX-License-Identifier: Apache-2.0

"""Guards that mutation testing found unpinned: the lifecycle filters on every
status write (a deleted/archived document must never be resurrected) and the
office-archive entry cap."""

from __future__ import annotations

import io
import zipfile

import asyncpg
import pytest

from raggie_workers.ingestion.parsing import DocumentLimitError, ParserLimits, _validate_ooxml
from raggie_workers.ingestion.status import DocumentStatusStore

LIVE = ("deleted_at IS NULL", "archived_at IS NULL")


class _RecordingDB:
    def __init__(self, missing: tuple[str, ...] = ()) -> None:
        self.missing = missing
        self.calls: list[tuple[str, tuple]] = []

    async def execute(self, sql, *args):
        if any(col in sql for col in self.missing):
            raise asyncpg.UndefinedColumnError(f'column "{self.missing[0]}" does not exist')
        self.calls.append((" ".join(sql.split()), args))


async def test_heartbeat_only_touches_a_live_processing_document() -> None:
    db = _RecordingDB()
    await DocumentStatusStore(db).touch("doc-1")
    ((sql, args),) = db.calls
    assert args == ("doc-1",)
    assert sql.startswith("UPDATE documents SET status = status WHERE id = $1::uuid")
    for predicate in ("status = 'PROCESSING'", *LIVE):
        assert predicate in sql


@pytest.mark.parametrize(
    ("missing", "sets", "unset", "args"),
    [
        (
            (),
            ("embedding_fingerprint = $2", "error_code = NULL", "error_params = NULL"),
            (),
            ("doc-1", "fp-1234"),
        ),
        (("error_code",), ("embedding_fingerprint = $2",), ("error_code",), ("doc-1", "fp-1234")),
        (
            ("error_code", "embedding_fingerprint"),
            (),
            ("error_code", "embedding_fingerprint"),
            ("doc-1",),
        ),
    ],
    ids=["current-schema", "before-0029", "before-0026"],
)
async def test_fingerprinted_success_keeps_its_guards_at_every_fallback(
    missing, sets, unset, args
) -> None:
    db = _RecordingDB(missing)
    await DocumentStatusStore(db).mark_success("doc-1", "fp-1234")
    ((sql, got),) = db.calls
    assert got == args
    assert "status = 'SUCCESS'" in sql and "error_message = NULL" in sql
    assert "WHERE id = $1::uuid" in sql
    for fragment in (*sets, *LIVE):
        assert fragment in sql
    for column in unset:
        assert column not in sql


def _ooxml(entries: int) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<w:document/>")
        for i in range(entries - 2):
            archive.writestr(f"word/media/{i}.bin", b"x")
    return buf.getvalue()


def test_archive_entry_cap_boundary() -> None:
    limits = ParserLimits(max_archive_entries=5)
    _validate_ooxml(_ooxml(5), "word/document.xml", limits)  # exactly at the cap: allowed
    with pytest.raises(DocumentLimitError) as caught:
        _validate_ooxml(_ooxml(6), "word/document.xml", limits)
    assert (caught.value.kind, caught.value.limit) == ("archive_entries", 5)
