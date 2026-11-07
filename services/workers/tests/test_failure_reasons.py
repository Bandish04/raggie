# SPDX-License-Identifier: Apache-2.0

"""Failure reasons stored on documents: a stable code + params the web renders
per language (contracts/document_errors.md), plus a clear English sentence in
error_message for the API and older clients. No internal hosts or URLs."""

import pickle

import httpx
import pytest

import raggie_workers.ingestion.consumer as consumer_module
from raggie_workers.ingestion.consumer import (
    FAILURE_CODES,
    IngestionConsumer,
    ObjectReadError,
    describe_failure,
)
from raggie_workers.ingestion.isolation import ParserCrashedError, ParseTimeoutError, _portable
from raggie_workers.ingestion.openai_embedder import FingerprintMismatch
from raggie_workers.ingestion.parsing import (
    DocumentLimitError,
    InvalidDocumentError,
    UnsupportedFormatError,
)


def _status_error(code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "http://embeddings.internal:8002/v1/embeddings")
    return httpx.HTTPStatusError("boom", request=request, response=httpx.Response(code))


@pytest.mark.parametrize(
    ("exc", "code", "params", "message"),
    [
        (
            DocumentLimitError("PDF has more than 2 pages", kind="pdf_pages", limit=2),
            "parse_limit",
            {"kind": "pdf_pages", "limit": 2},
            "PDF has more than 2 pages.",
        ),
        (
            InvalidDocumentError("file does not match its declared office format"),
            "parse_invalid",
            {},
            "File does not match its declared office format.",
        ),
        (
            UnsupportedFormatError("unsupported file type: .zip", extension=".zip"),
            "unsupported_format",
            {"extension": ".zip"},
            "Unsupported file type: .zip.",
        ),
        (
            ParseTimeoutError(120),
            "parse_timeout",
            {"seconds": 120},
            "Document parsing exceeded 120 seconds.",
        ),
        (
            ParserCrashedError(-9),
            "parser_crashed",
            {"exit_code": -9},
            "Document parser exited unexpectedly (exit code -9).",
        ),
        (
            FingerprintMismatch("aaaa1111", "bbbb2222"),
            "fingerprint_mismatch",
            {"expected": "aaaa1111", "actual": "bbbb2222"},
            "Document is indexed with embedding profile aaaa1111 but the gateway now embeds "
            "with bbbb2222; re-embed required.",
        ),
        (
            _status_error(503),
            "embeddings_http",
            {"status": 503},
            "The embeddings service answered HTTP 503; embedding failed.",
        ),
        (
            httpx.ConnectError("refused"),
            "embeddings_unreachable",
            {},
            "The embeddings service could not be reached; embedding failed.",
        ),
        (
            ObjectReadError(),
            "object_read",
            {},
            "The uploaded file could not be read from object storage.",
        ),
        (
            RuntimeError("password=hunter2 at db.internal:5432"),
            "unexpected",
            {},
            (
                "Ingestion failed unexpectedly (RuntimeError); "
                "details are in the ingestion worker logs."
            ),
        ),
    ],
)
def test_failures_map_to_code_params_and_message(exc, code, params, message) -> None:
    reason = describe_failure(exc)
    assert (reason.code, reason.params, reason.message) == (code, params, message)
    assert reason.code in FAILURE_CODES
    assert "internal" not in reason.message and "hunter2" not in reason.message


def test_vector_database_errors() -> None:
    from qdrant_client.http.exceptions import ResponseHandlingException

    reason = describe_failure(ResponseHandlingException(OSError("timed out at qdrant:6333")))
    assert (reason.code, reason.params) == ("vector_store", {})
    assert reason.message == "The vector database did not accept the chunks; indexing failed."


def test_message_is_bounded() -> None:
    assert len(describe_failure(DocumentLimitError("x" * 5000)).message) <= 500


@pytest.mark.parametrize(
    "exc",
    [
        DocumentLimitError("PDF has more than 2 pages", kind="pdf_pages", limit=2),
        UnsupportedFormatError("unsupported file type: .zip", extension=".zip"),
        ParseTimeoutError(30),
        ParserCrashedError(-9),
    ],
)
def test_structured_parser_errors_survive_the_process_boundary(exc) -> None:
    # The parser child pickles its exception; _portable() must keep it (not
    # degrade it to RuntimeError) and the params must survive.
    assert _portable(exc) is exc
    back = pickle.loads(pickle.dumps(exc))
    assert type(back) is type(exc) and str(back) == str(exc)
    assert describe_failure(back).params == describe_failure(exc).params


def test_code_list_matches_the_contract() -> None:
    from pathlib import Path

    contract = Path(__file__).resolve().parents[3] / "contracts" / "document_errors.md"
    text = contract.read_text(encoding="utf-8")
    for code in FAILURE_CODES:
        assert f"`{code}`" in text, code


class _Status:
    def __init__(self) -> None:
        self.failed: list[dict] = []

    async def is_live(self, _doc_id) -> bool:
        return True

    async def mark_processing(self, _doc_id) -> None:
        return None

    async def touch(self, _doc_id) -> None:
        return None

    async def mark_success(self, _doc_id, _fp=None) -> None:
        return None

    async def mark_failed(self, doc_id, error, *, terminal=False, code=None, params=None):
        self.failed.append({"error": error, "code": code, "params": params, "terminal": terminal})


class _Bus:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def publish(self, _topic, payload) -> None:
        self.events.append(payload)


class _Store:
    async def download_to_file(self, _key, _path) -> None:
        return None


async def test_consumer_stores_code_params_and_message(monkeypatch) -> None:
    async def failing(**_kw):
        raise DocumentLimitError("PDF has more than 3 pages", kind="pdf_pages", limit=3)

    monkeypatch.setattr(consumer_module, "process_document", failing)
    status, bus = _Status(), _Bus()
    consumer = IngestionConsumer(
        bus=bus, object_store=_Store(), embedder=None, vector_store=None, status=status
    )
    await consumer.handle(
        {
            "document_id": "d",
            "workspace_id": "w",
            "filename": "f.pdf",
            "object_key": "k",
            "embedding_dim": 8,
        }
    )
    assert status.failed == [
        {
            "error": "PDF has more than 3 pages.",
            "code": "parse_limit",
            "params": {"kind": "pdf_pages", "limit": 3},
            "terminal": False,
        }
    ]
    assert bus.events[-1] == {
        "document_id": "d",
        "error": "PDF has more than 3 pages.",
        "error_code": "parse_limit",
    }


async def test_fingerprint_mismatch_is_terminal_with_code(monkeypatch) -> None:
    async def failing(**_kw):
        raise FingerprintMismatch("aaaa1111", "bbbb2222")

    monkeypatch.setattr(consumer_module, "process_document", failing)
    status = _Status()
    consumer = IngestionConsumer(
        bus=_Bus(), object_store=_Store(), embedder=None, vector_store=None, status=status
    )
    await consumer.handle(
        {
            "document_id": "d",
            "workspace_id": "w",
            "filename": "f.pdf",
            "object_key": "k",
            "embedding_dim": 8,
        }
    )
    assert status.failed[0]["code"] == "fingerprint_mismatch"
    assert status.failed[0]["terminal"] is True


class _FakeDB:
    """Rejects statements touching columns the (old) schema does not have."""

    def __init__(self, missing: set[str]) -> None:
        self.missing = missing
        self.attempts = 0
        self.executed: list[tuple[str, tuple]] = []

    async def execute(self, sql, *args):
        import asyncpg

        self.attempts += 1
        for col in sorted(self.missing):
            if col in sql:
                raise asyncpg.UndefinedColumnError(
                    f'column "{col}" of relation "documents" does not exist'
                )
        self.executed.append((sql, args))


async def test_status_store_writes_code_and_params_as_jsonb() -> None:
    from raggie_workers.ingestion.status import DocumentStatusStore

    db = _FakeDB(set())
    await DocumentStatusStore(db).mark_failed(
        "d",
        "PDF has more than 3 pages.",
        code="parse_limit",
        params={"kind": "pdf_pages", "limit": 3},
    )
    sql, args = db.executed[-1]
    assert "error_code = $3" in sql and "error_params = $4::jsonb" in sql
    assert args == (
        "d",
        "PDF has more than 3 pages.",
        "parse_limit",
        '{"kind": "pdf_pages", "limit": 3}',
    )


@pytest.mark.parametrize(
    ("missing", "expect_fingerprint"),
    [
        ({"error_code"}, True),  # 0026 applied, 0029 not yet
        ({"error_code", "embedding_fingerprint"}, False),  # neither applied
    ],
)
async def test_status_store_tolerates_pending_migrations(missing, expect_fingerprint) -> None:
    from raggie_workers.ingestion.status import DocumentStatusStore

    db = _FakeDB(missing)
    store = DocumentStatusStore(db)
    await store.mark_failed("d", "boom.", code="unexpected", params={})
    await store.mark_failed("d", "boom.", terminal=True, code="fingerprint_mismatch", params={})
    await store.mark_processing("d")
    await store.mark_success("d", "abcd1234")
    assert len(db.executed) == 4  # every call landed on a supported statement
    assert ("embedding_fingerprint" in db.executed[-1][0]) is expect_fingerprint
    assert all("error_code" not in sql for sql, _ in db.executed)


async def test_status_store_does_not_retry_other_db_errors() -> None:
    import asyncpg

    from raggie_workers.ingestion.status import DocumentStatusStore

    class _BrokenDB(_FakeDB):
        async def execute(self, sql, *args):
            self.attempts += 1
            raise asyncpg.CheckViolationError("new row violates check constraint")

    db = _BrokenDB(set())
    with pytest.raises(asyncpg.CheckViolationError):
        await DocumentStatusStore(db).mark_failed("d", "boom.", code="unexpected", params={})
    assert db.attempts == 1  # never downgraded to an older statement


async def test_status_store_warns_once_naming_the_missing_column(caplog) -> None:
    from raggie_workers.ingestion.status import DocumentStatusStore

    store = DocumentStatusStore(_FakeDB({"error_code"}))
    with caplog.at_level("WARNING", logger="ingestion.status"):
        for _ in range(3):
            await store.mark_failed("d", "boom.", code="unexpected", params={})
            await store.mark_processing("d")
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1
    assert "error_code" in warnings[0].getMessage()


# The extension comes from the uploaded file name: only a short, plain suffix
# may reach error_params (rendered by the web UI) or the stored message.
@pytest.mark.parametrize(
    ("extension", "want"),
    [
        (".zip", ".zip"),
        (".tar.gz", ".tar.gz"),
        (".7z", ".7z"),
        (".a" * 8, ".a.a.a.a.a.a.a.a"),  # 16 chars: still allowed
        ("." + "x" * 16, "unknown"),  # 17 chars
        (".<img src=x onerror=alert(1)>", "unknown"),
        (".ZIP", "unknown"),  # the parser lower-cases; anything else is foreign
        (".zi p", "unknown"),
        (".zip\n", "unknown"),
    ],
)
def test_unsupported_extension_is_capped(extension, want) -> None:
    reason = describe_failure(UnsupportedFormatError("unsupported", extension=extension))
    assert reason.params == {"extension": want}


@pytest.mark.parametrize("name", ["report.<script>alert(1)", "a." + "y" * 40])
def test_parser_never_echoes_a_hostile_extension(name) -> None:
    from raggie_workers.ingestion.parsing import extract_text

    with pytest.raises(UnsupportedFormatError) as caught:
        extract_text(name, b"data")
    assert caught.value.extension == "unknown"
    assert "<script>" not in str(caught.value) and "yyyy" not in str(caught.value)


def test_path_parser_never_echoes_a_hostile_extension(tmp_path) -> None:
    from raggie_workers.ingestion.parsing import extract_text_from_path

    path = tmp_path / "report.<b>bold"
    path.write_bytes(b"data")
    with pytest.raises(UnsupportedFormatError) as caught:
        extract_text_from_path(path.name, str(path))
    assert caught.value.extension == "unknown" and "<b>" not in str(caught.value)
