# SPDX-License-Identifier: Apache-2.0

from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport

from raggie_control_plane.api.deps import get_conn, get_current_user
from raggie_control_plane.db.repositories import OrganizationRepo, WorkspaceRepo
from raggie_control_plane.main import app
from raggie_control_plane.models import Role, User


@pytest_asyncio.fixture
async def super_client(conn):
    org = await OrganizationRepo(conn).create("Acme")
    su = User(
        id=uuid4(),
        org_id=org.id,
        email="su@raggie.test",
        role=Role.SUPER_ADMIN,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    async def _conn_override():
        yield conn

    app.dependency_overrides[get_conn] = _conn_override
    app.dependency_overrides[get_current_user] = lambda: su
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, org, conn
    app.dependency_overrides.clear()


async def test_analytics_summary(super_client) -> None:
    client, org, conn = super_client
    ws = await WorkspaceRepo(conn).create(org.id, "W", "INTERNAL")
    await conn.execute(
        "INSERT INTO documents (workspace_id, filename, file_size, status, qdrant_collection_name)"
        " VALUES ($1,'a.pdf',10,'SUCCESS','raggie_chunks_d384'),"
        "        ($1,'b.pdf',20,'FAILED','raggie_chunks_d384'),"
        "        ($1,'c.pdf',30,'PROCESSING','raggie_chunks_d384')",
        ws.id,
    )
    cid = await conn.fetchval(
        "INSERT INTO conversations (workspace_id, is_flagged) VALUES ($1, TRUE) RETURNING id",
        ws.id,
    )
    await conn.execute(
        "INSERT INTO messages (conversation_id, sender, content, used_tokens)"
        " VALUES ($1,'USER','hi',0),($1,'BOT','yo',42)",
        cid,
    )

    r = await client.get("/api/v1/admin/analytics")
    assert r.status_code == 200
    d = r.json()
    assert d["workspaces"] == 1
    assert d["documents"] == {
        "total": 3,
        "pending": 0,
        "processing": 1,
        "success": 1,
        "failed": 1,
    }
    assert d["conversations"] == 1
    assert d["flagged"] == 1
    assert d["messages"] == 2
    assert d["tokens_used"] == 42
    assert len(d["activity"]) == 7
    assert sum(p["messages"] for p in d["activity"]) == 2  # both messages are today


async def test_analytics_empty_is_zero(super_client) -> None:
    client, _org, _conn = super_client
    r = await client.get("/api/v1/admin/analytics")
    assert r.status_code == 200
    d = r.json()
    assert d["workspaces"] == 0
    assert d["documents"]["total"] == 0
    assert d["messages"] == 0
    assert len(d["activity"]) == 7


async def test_flagged_conversations(super_client) -> None:
    client, org, conn = super_client
    ws = await WorkspaceRepo(conn).create(org.id, "W", "INTERNAL")
    flagged = await conn.fetchval(
        "INSERT INTO conversations (workspace_id, evaluation_score, is_flagged)"
        " VALUES ($1, 0.2, TRUE) RETURNING id",
        ws.id,
    )
    await conn.execute(
        "INSERT INTO messages (conversation_id, sender, content)"
        " VALUES ($1,'USER','why is the sky green?')",
        flagged,
    )
    await conn.execute(
        "INSERT INTO messages ("
        " conversation_id, sender, content, evaluation_score, faithfulness_score,"
        " citation_validity_score, citation_coverage_score, evaluation_flagged, evaluated_at)"
        " VALUES ($1,'BOT','unsupported [2]',0.2,0.4,0.0,0.0,TRUE,now())",
        flagged,
    )
    # A healthy conversation must not appear.
    await conn.execute(
        "INSERT INTO conversations (workspace_id, evaluation_score, is_flagged)"
        " VALUES ($1, 0.95, FALSE)",
        ws.id,
    )

    r = await client.get("/api/v1/admin/conversations/flagged")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["evaluation_score"] == pytest.approx(0.2, abs=1e-4)
    assert rows[0]["faithfulness_score"] == pytest.approx(0.4, abs=1e-4)
    assert rows[0]["citation_validity_score"] == pytest.approx(0.0, abs=1e-4)
    assert rows[0]["citation_coverage_score"] == pytest.approx(0.0, abs=1e-4)
    assert rows[0]["preview"] == "why is the sky green?"
