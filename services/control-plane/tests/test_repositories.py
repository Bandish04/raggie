# SPDX-License-Identifier: Apache-2.0

import pytest

from raggie_control_plane.db.repositories import (
    DocumentRepo,
    MembershipRepo,
    OrganizationRepo,
    SkillsRepo,
    TeamRepo,
    UserRepo,
    WorkspaceRepo,
)
from raggie_control_plane.models import Role, WorkspaceType


async def test_org_user_workspace_crud(conn) -> None:
    org = await OrganizationRepo(conn).create("Acme")
    assert org.name == "Acme"

    user = await UserRepo(conn).create(
        "admin@acme.example", "hashed", "WORKSPACE_ADMIN", org_id=org.id
    )
    assert user.email == "admin@acme.example"
    assert user.role == Role.WORKSPACE_ADMIN

    ws = await WorkspaceRepo(conn).create(org.id, "Support", "EXTERNAL")
    assert ws.type == WorkspaceType.EXTERNAL
    # JSONB decodes to a Python list, not a raw string.
    assert ws.cors_allowed_origins == []
    assert ws.temperature == pytest.approx(0.3)


async def test_get_by_email_and_password_hash(conn) -> None:
    org = await OrganizationRepo(conn).create("Acme")
    repo = UserRepo(conn)
    await repo.create("u@acme.example", "secret-hash", "STAFF", org_id=org.id)

    fetched = await repo.get_by_email("u@acme.example")
    assert fetched is not None and fetched.org_id == org.id
    assert await repo.get_password_hash("u@acme.example") == "secret-hash"
    assert await repo.get_by_email("missing@acme.example") is None


async def test_team_closure_grants_inherited_workspace_access(conn) -> None:
    org = await OrganizationRepo(conn).create("Acme")
    teams = TeamRepo(conn)
    eng = await teams.create(org.id, "Engineering")  # top-level
    backend = await teams.create(org.id, "Backend", parent_team_id=eng.id)
    platform = await teams.create(org.id, "Platform", parent_team_id=backend.id)

    ws = await WorkspaceRepo(conn).create(org.id, "Platform Docs", "INTERNAL", team_id=platform.id)
    user = await UserRepo(conn).create("lead@acme.example", "h", "WORKSPACE_ADMIN", org_id=org.id)

    members = MembershipRepo(conn)
    # Member of the top-level team -> inherited access to a deeply-nested workspace.
    await members.add_team_member(eng.id, user.id, "WORKSPACE_ADMIN")
    effective = await members.effective_workspace_ids(user.id)
    assert ws.id in effective


async def test_team_descendants(conn) -> None:
    org = await OrganizationRepo(conn).create("Acme")
    teams = TeamRepo(conn)
    eng = await teams.create(org.id, "Engineering")
    backend = await teams.create(org.id, "Backend", parent_team_id=eng.id)
    platform = await teams.create(org.id, "Platform", parent_team_id=backend.id)

    descendants = set(await teams.descendant_ids(eng.id))
    assert {eng.id, backend.id, platform.id} == descendants


async def test_direct_workspace_membership(conn) -> None:
    org = await OrganizationRepo(conn).create("Acme")
    ws = await WorkspaceRepo(conn).create(org.id, "HR", "INTERNAL")
    user = await UserRepo(conn).create("staff@acme.example", "h", "STAFF", org_id=org.id)

    members = MembershipRepo(conn)
    await members.add_workspace_member(ws.id, user.id, "STAFF")
    effective = await members.effective_workspace_ids(user.id)
    assert effective == [ws.id]


async def test_skill_policy_is_versioned_and_audit_survives_delete(conn) -> None:
    org = await OrganizationRepo(conn).create("Skill Governance")
    user = await UserRepo(conn).create(
        "skill-admin@example.com", "h", "WORKSPACE_ADMIN", org_id=org.id
    )
    repo = SkillsRepo(conn)

    skill = await repo.create(
        org.id,
        name="Contract Analyst",
        slug="contract",
        instructions="Use version one.",
        allowed_tools=["web_search"],
        created_by=user.id,
    )
    assert skill.version == 1
    assert len(skill.policy_hash) == 64
    assert skill.allowed_tools == ["web_search"]

    versions = await repo.list_versions(skill.id)
    assert [item.version for item in versions] == [1]
    assert versions[0].policy_hash == skill.policy_hash

    updated = await repo.update(
        skill.id,
        actor_id=user.id,
        instructions="Use version two.",
        allowed_tools=["deep_research"],
    )
    assert updated is not None
    assert updated.version == 2
    assert updated.policy_hash != skill.policy_hash

    versions = await repo.list_versions(skill.id)
    assert [item.version for item in versions] == [2, 1]
    assert versions[0].created_by == user.id

    restored = await repo.restore_version(skill.id, 1, actor_id=user.id)
    assert restored is not None
    assert restored.version == 3
    assert restored.instructions == "Use version one."
    assert restored.allowed_tools == ["web_search"]

    assert await repo.delete(skill.id, actor_id=user.id)
    assert await repo.get(skill.id) is None
    # Immutable snapshots have no FK to the mutable skill row, so deletion never
    # destroys the execution audit trail.
    assert len(await repo.list_versions(skill.id)) == 3


async def test_failed_document_retry_ignores_soft_deleted(conn) -> None:
    org = await OrganizationRepo(conn).create("Acme")
    ws = await WorkspaceRepo(conn).create(org.id, "Docs", "INTERNAL")
    docs = DocumentRepo(conn)
    live = await docs.create(ws.id, "live.pdf", 10, "raggie_chunks_d1024")
    gone = await docs.create(ws.id, "gone.pdf", 10, "raggie_chunks_d1024")
    await conn.execute(
        "UPDATE documents SET status = 'FAILED' WHERE id = ANY($1::uuid[])", [live.id, gone.id]
    )
    assert await docs.soft_delete(gone.id)

    failed = {d.id for d in await docs.list_failed()}
    assert live.id in failed and gone.id not in failed

    # A deleted document is never re-armed for ingestion (nor fetched by id).
    await docs.reset_for_retry(gone.id, "raggie_chunks_d768", "5e1f00d2")
    await docs.reset_for_reindex(gone.id, "raggie_chunks_d768", "5e1f00d2")
    row = await conn.fetchrow(
        "SELECT status, qdrant_collection_name FROM documents WHERE id = $1", gone.id
    )
    assert row["status"] == "FAILED" and row["qdrant_collection_name"] == "raggie_chunks_d1024"
    assert await docs.get(gone.id) is None


async def test_rearming_a_document_clears_its_error_code_and_params(conn) -> None:
    """A re-armed document must not keep showing the previous failure's code
    (the web renders error_code/error_params in the viewer's language)."""
    org = await OrganizationRepo(conn).create("Acme")
    ws = await WorkspaceRepo(conn).create(org.id, "Docs", "INTERNAL")
    docs = DocumentRepo(conn)
    for reset in (docs.reset_for_retry, docs.reset_for_reindex):
        doc = await docs.create(ws.id, f"{reset.__name__}.pdf", 10, "raggie_chunks_d1024")
        await conn.execute(
            "UPDATE documents SET status = 'FAILED', error_message = 'parse timed out',"
            " error_code = 'parse_timeout', error_params = '{\"seconds\": 120}'::jsonb"
            " WHERE id = $1",
            doc.id,
        )
        await reset(doc.id, "raggie_chunks_d768", "5e1f00d2")
        row = await conn.fetchrow(
            "SELECT status, error_message, error_code, error_params FROM documents WHERE id = $1",
            doc.id,
        )
        assert row["status"] == "PENDING", reset.__name__
        assert row["error_message"] is None, reset.__name__
        assert row["error_code"] is None and row["error_params"] is None, reset.__name__


async def test_audit_metadata_stored_as_json_object(conn) -> None:
    from raggie_control_plane.db.repositories import AuditRepo

    await AuditRepo(conn).record("test.audit", target="t-json", metadata={"k": "v", "n": 1})
    row = await conn.fetchrow(
        "SELECT jsonb_typeof(metadata) AS kind, metadata FROM audit_log WHERE target = 't-json'"
    )
    assert row["kind"] == "object" and row["metadata"] == {"k": "v", "n": 1}


async def test_no_not_null_column_has_an_on_delete_set_null_fk(conn) -> None:
    """A NOT NULL column behind ON DELETE SET NULL / SET DEFAULT makes deleting
    the referenced row fail; the schema must never contain that contradiction."""
    rows = await conn.fetch(
        "SELECT con.conrelid::regclass::text AS tbl, a.attname"
        " FROM pg_constraint con"
        " JOIN LATERAL unnest(con.conkey) k(attnum) ON true"
        " JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.attnum"
        " WHERE con.contype = 'f' AND con.confdeltype IN ('n', 'd') AND a.attnotnull"
    )
    assert [f"{r['tbl']}.{r['attname']}" for r in rows] == []


async def _user_with_feedback(conn):
    org = await OrganizationRepo(conn).create("Feedback Org")
    ws = await WorkspaceRepo(conn).create(org.id, "WS", "INTERNAL")
    user = await UserRepo(conn).create("fb@acme.example", "h", "STAFF", org_id=org.id)
    conv = await conn.fetchval(
        "INSERT INTO conversations (workspace_id, user_id) VALUES ($1, $2) RETURNING id",
        ws.id,
        user.id,
    )
    msg = await conn.fetchval(
        "INSERT INTO messages (conversation_id, sender, content) VALUES ($1, 'BOT', 'hi')"
        " RETURNING id",
        conv,
    )
    await conn.execute(
        "INSERT INTO message_feedback (message_id, user_id, rating) VALUES ($1, $2, 'up')"
        " ON CONFLICT (message_id, user_id) DO UPDATE SET rating = EXCLUDED.rating",
        msg,
        user.id,
    )
    return org, user, msg


async def test_deleting_user_keeps_anonymized_feedback(conn) -> None:
    _org, user, msg = await _user_with_feedback(conn)
    assert await UserRepo(conn).delete(user.id)
    row = await conn.fetchrow("SELECT user_id FROM message_feedback WHERE message_id = $1", msg)
    assert row is not None and row["user_id"] is None


async def test_deleting_org_with_feedback_succeeds(conn) -> None:
    org, _user, _msg = await _user_with_feedback(conn)
    await conn.execute("DELETE FROM organizations WHERE id = $1", org.id)
    assert await OrganizationRepo(conn).get(org.id) is None
