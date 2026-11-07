# SPDX-License-Identifier: Apache-2.0

"""documents.error_code / error_params (0029): stable failure codes the web
renders per language; the document API exposes them."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from raggie_control_plane.models import Document

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


def test_document_model_exposes_code_and_params() -> None:
    now = datetime.now(UTC)
    doc = Document(
        id=uuid4(),
        workspace_id=uuid4(),
        filename="big.pdf",
        file_size=1,
        status="FAILED",
        qdrant_collection_name="raggie_chunks_d1024",
        error_message="PDF has more than 3 pages.",
        error_code="parse_limit",
        error_params={"kind": "pdf_pages", "limit": 3},
        created_at=now,
        updated_at=now,
    )
    body = doc.model_dump(mode="json")
    assert body["error_code"] == "parse_limit"
    assert body["error_params"] == {"kind": "pdf_pages", "limit": 3}
    legacy = Document(
        id=uuid4(),
        workspace_id=uuid4(),
        filename="a",
        file_size=1,
        status="FAILED",
        qdrant_collection_name="c",
        created_at=now,
        updated_at=now,
    )
    assert legacy.error_code is None and legacy.error_params is None


def test_0029_adds_nullable_columns_only() -> None:
    up = (MIGRATIONS / "0029_document_error_codes.up.sql").read_text(encoding="utf-8")
    down = (MIGRATIONS / "0029_document_error_codes.down.sql").read_text(encoding="utf-8")
    assert up.startswith("-- SPDX-License-Identifier: Apache-2.0")
    assert down.startswith("-- SPDX-License-Identifier: Apache-2.0")
    assert "ADD COLUMN IF NOT EXISTS error_code TEXT" in up
    assert "ADD COLUMN IF NOT EXISTS error_params JSONB" in up
    assert "NOT NULL" not in up and "UPDATE " not in up.upper()
    assert "DROP COLUMN IF EXISTS error_code" in down
    assert "DROP COLUMN IF EXISTS error_params" in down


def test_contract_lists_every_code() -> None:
    contract = Path(__file__).resolve().parents[3] / "contracts" / "document_errors.md"
    text = contract.read_text(encoding="utf-8")
    for code in (
        "parse_limit",
        "parse_invalid",
        "unsupported_format",
        "parse_timeout",
        "parser_crashed",
        "fingerprint_mismatch",
        "embeddings_http",
        "embeddings_unreachable",
        "vector_store",
        "object_read",
        "unexpected",
    ):
        assert f"| `{code}` |" in text, code


async def test_0029_columns_round_trip_and_reverse(conn) -> None:
    """DB-backed (CI)."""
    from raggie_control_plane.db.repositories import (
        DocumentRepo,
        OrganizationRepo,
        WorkspaceRepo,
    )

    up = (MIGRATIONS / "0029_document_error_codes.up.sql").read_text(encoding="utf-8")
    down = (MIGRATIONS / "0029_document_error_codes.down.sql").read_text(encoding="utf-8")
    await conn.execute(up)  # idempotent on an already-migrated DB
    org = await OrganizationRepo(conn).create("Codes")
    ws = await WorkspaceRepo(conn).create(org.id, "Codes", "INTERNAL")
    doc_id = await conn.fetchval(
        "INSERT INTO documents (workspace_id, filename, file_size, qdrant_collection_name,"
        " status, error_message, error_code, error_params)"
        " VALUES ($1, 'big.pdf', 1, 'raggie_chunks_d1024', 'FAILED', 'x', 'parse_limit',"
        " $2::jsonb) RETURNING id",
        ws.id,
        {"kind": "pdf_pages", "limit": 3},
    )
    doc = await DocumentRepo(conn).get(doc_id)
    assert (doc.error_code, doc.error_params) == ("parse_limit", {"kind": "pdf_pages", "limit": 3})
    await conn.execute(down)
    await conn.execute(down)  # idempotent
    await conn.execute(up)
