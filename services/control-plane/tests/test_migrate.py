# SPDX-License-Identifier: Apache-2.0

import hashlib
import json
from pathlib import Path

from raggie_control_plane.api.workspaces import _validate_origins
from raggie_control_plane.config import settings
from raggie_control_plane.db.migrate import apply_migrations
from raggie_control_plane.db.repositories import OrganizationRepo, WorkspaceRepo
from raggie_control_plane.embeddings_profile import LEGACY_COLLECTION, LEGACY_FINGERPRINT


async def test_core_tables_exist(conn) -> None:
    rows = await conn.fetch(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
    )
    names = {r["table_name"] for r in rows}
    expected = {
        "organizations",
        "users",
        "teams",
        "team_closure",
        "team_members",
        "workspaces",
        "workspace_members",
        "documents",
        "conversations",
        "messages",
        "invites",
        "audit_log",
        "system_settings",
    }
    assert expected <= names


async def test_migrations_are_idempotent(conn) -> None:
    # The conftest fixture already applied migrations; re-applying is a no-op.
    newly = await apply_migrations(conn, settings.migrations_dir)
    assert newly == []
    versions = {r["version"] for r in await conn.fetch("SELECT version FROM schema_migrations")}
    assert "0001" in versions


async def test_unowned_llmaas_default_url_is_gone(conn) -> None:
    """0001 defaulted system_settings.llmaas_base_url to a domain we don't own;
    nothing reads the llmaas_* columns, so 0025 drops them everywhere."""
    rows = await conn.fetch(
        "SELECT table_name, column_name FROM information_schema.columns"
        " WHERE table_schema = current_schema()"
        "   AND column_name IN ('llmaas_base_url', 'llmaas_api_key_ref')"
    )
    assert [(r["table_name"], r["column_name"]) for r in rows] == []
    defaults = await conn.fetch(
        "SELECT table_name, column_name FROM information_schema.columns"
        " WHERE table_schema = current_schema() AND column_default ILIKE '%llmaas.ai%'"
    )
    assert defaults == []


async def test_messages_interrupted_reason_column(conn) -> None:
    """The edge marks a BOT answer cut off by a replica drain ('shutdown_drain')
    and resumes it; 0025 adds the nullable column it writes on every finalize."""
    row = await conn.fetchrow(
        "SELECT data_type, is_nullable, column_default FROM information_schema.columns"
        " WHERE table_schema = current_schema()"
        "   AND table_name = 'messages' AND column_name = 'interrupted_reason'"
    )
    assert row is not None
    assert (row["data_type"], row["is_nullable"], row["column_default"]) == ("text", "YES", None)


_MIGRATIONS = Path(settings.migrations_dir)


def _legacy_fingerprint() -> str:
    """Recompute the legacy profile's fingerprint exactly like services/embeddings
    (providers/fingerprint.py): sha256 of the canonical profile JSON (sorted keys,
    no whitespace), first 8 hex chars. Imported code can't cross services."""
    profile = {
        "provider": "local",
        "model": "intfloat/multilingual-e5-large",
        "dim": 1024,
        "query_prefix": "query: ",
        "passage_prefix": "passage: ",
        "request_extra": {},
        "query_extra": {},
        "passage_extra": {},
    }
    canonical = json.dumps(profile, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:8]


def test_legacy_fingerprint_matches_the_gateway_algorithm() -> None:
    assert _legacy_fingerprint() == LEGACY_FINGERPRINT == "2872ae6a"
    up = (_MIGRATIONS / "0026_embedding_fingerprint.up.sql").read_text(encoding="utf-8")
    assert f"'{LEGACY_FINGERPRINT}'" in up
    assert f"'{LEGACY_COLLECTION}'" in up


async def test_0026_adds_embedding_fingerprint_columns(conn) -> None:
    rows = await conn.fetch(
        "SELECT table_name, column_name, data_type FROM information_schema.columns"
        " WHERE table_schema = current_schema()"
        "   AND column_name IN ('embedding_fingerprint', 'embedding_profile')"
    )
    assert {(r["table_name"], r["column_name"], r["data_type"]) for r in rows} == {
        ("system_settings", "embedding_fingerprint", "text"),
        ("system_settings", "embedding_profile", "jsonb"),
        ("documents", "embedding_fingerprint", "text"),
    }


async def test_0026_backfills_only_legacy_collection_rows_and_is_reversible(conn) -> None:
    up = (_MIGRATIONS / "0026_embedding_fingerprint.up.sql").read_text(encoding="utf-8")
    down = (_MIGRATIONS / "0026_embedding_fingerprint.down.sql").read_text(encoding="utf-8")
    org = await OrganizationRepo(conn).create("Mig")
    ws = await WorkspaceRepo(conn).create(org.id, "Mig", "INTERNAL")

    await conn.execute(down)
    ids = {}
    for name, collection in (
        ("legacy", "raggie_chunks_d1024"),
        ("other_dim", "raggie_chunks_d384"),
        ("profiled", "raggie_chunks_d1024_5e1f00d2"),
    ):
        ids[name] = await conn.fetchval(
            "INSERT INTO documents (workspace_id, filename, file_size, qdrant_collection_name)"
            " VALUES ($1, $2, 1, $3) RETURNING id",
            ws.id,
            name,
            collection,
        )
    await conn.execute(up)
    await conn.execute(up)  # idempotent

    rows = await conn.fetch(
        "SELECT id, embedding_fingerprint FROM documents WHERE id = ANY($1::uuid[])"
        " AND deleted_at IS NULL",
        list(ids.values()),
    )
    by_id = {r["id"]: r["embedding_fingerprint"] for r in rows}
    assert by_id == {ids["legacy"]: "2872ae6a", ids["other_dim"]: None, ids["profiled"]: None}

    await conn.execute(down)
    await conn.execute(down)  # idempotent
    gone = await conn.fetchval(
        "SELECT count(*) FROM information_schema.columns WHERE table_schema = current_schema()"
        " AND column_name IN ('embedding_fingerprint', 'embedding_profile')"
    )
    assert gone == 0
    assert await _embedding_dim_columns(conn) == {"organizations", "workspaces"}  # restored
    await conn.execute(up)
    assert await _embedding_dim_columns(conn) == set()


async def _embedding_dim_columns(conn) -> set[str]:
    rows = await conn.fetch(
        "SELECT table_name FROM information_schema.columns"
        " WHERE table_schema = current_schema() AND column_name = 'embedding_dim'"
    )
    return {r["table_name"] for r in rows}


async def test_0026_drops_the_unused_per_tenant_embedding_dim(conn) -> None:
    """The gateway's profile decides the dimension; nothing reads these anymore."""
    assert await _embedding_dim_columns(conn) == set()


async def test_0025_normalizes_stored_widget_origins(conn) -> None:
    """Origins saved before normalization (mixed case, default port, trailing
    slash) never matched the browser's Origin at the edge; 0025 rewrites them in
    the serialized form, deduplicated, order kept. Needs Postgres (CI)."""
    org = await OrganizationRepo(conn).create("Acme")
    ws = await WorkspaceRepo(conn).create(org.id, "Support", "EXTERNAL")
    stored = [
        "https://Example.com:443/",
        "HTTP://LOCALHOST:80",
        "https://example.com",
        "http://a.com:08080/",
        "http://b.com:443",
        "https://c.com:0443",
    ]
    # The pool's jsonb codec encodes the list.
    await conn.execute(
        "UPDATE workspaces SET cors_allowed_origins = $1::jsonb WHERE id = $2", stored, ws.id
    )
    up = (Path(settings.migrations_dir) / "0025_drop_llmaas_defaults.up.sql").read_text()

    for _ in range(2):  # idempotent
        await conn.execute(up)
        repaired = await conn.fetchval(
            "SELECT cors_allowed_origins FROM workspaces WHERE id = $1", ws.id
        )
        assert repaired == [
            "https://example.com",
            "http://localhost",
            "http://a.com:8080",
            "http://b.com:443",
            "https://c.com",
        ]
    # The SQL repair agrees with the write-path normalizer.
    assert repaired == _validate_origins(stored)


async def test_0027_memory_flag_defaults_off_for_every_workspace(conn) -> None:
    up = (_MIGRATIONS / "0027_memory_toggle.up.sql").read_text(encoding="utf-8")
    down = (_MIGRATIONS / "0027_memory_toggle.down.sql").read_text(encoding="utf-8")
    col = await conn.fetchrow(
        "SELECT is_nullable, column_default FROM information_schema.columns"
        " WHERE table_schema = current_schema() AND table_name = 'workspaces'"
        "   AND column_name = 'memory_enabled'"
    )
    assert col["is_nullable"] == "NO" and col["column_default"] == "false"

    await conn.execute(down)
    org = await OrganizationRepo(conn).create("Pre-0027")
    existing = await conn.fetchval(
        "INSERT INTO workspaces (org_id, name, type) VALUES ($1, 'old', 'INTERNAL') RETURNING id",
        org.id,
    )
    await conn.execute(up)
    await conn.execute(up)  # idempotent
    # Privacy-first: existing workspaces do not start remembering users either.
    assert (
        await conn.fetchval("SELECT memory_enabled FROM workspaces WHERE id = $1", existing)
        is False
    )
    await conn.execute(down)
    await conn.execute(down)  # idempotent
    await conn.execute(up)
