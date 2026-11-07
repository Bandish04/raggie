# SPDX-License-Identifier: Apache-2.0

"""`python -m raggie_control_plane.reindex`: re-publish every live document after
a restore without vectors (scripts/restore.sh --reindex)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from embeddings_stub import CLOUD_INFO, unknown_profile

from raggie_control_plane import reindex
from raggie_control_plane.db.repositories import DocumentRepo, OrganizationRepo, WorkspaceRepo
from raggie_control_plane.embeddings_profile import GatewayUnavailableError


class RecordingPublisher:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def publish(self, topic: str, payload: dict) -> str:
        self.events.append((topic, payload))
        return "1-0"


async def _platform(conn, stored: str | None = "2872ae6a"):
    await conn.execute("UPDATE documents SET deleted_at = now() WHERE deleted_at IS NULL")
    await conn.execute("INSERT INTO system_settings(id) VALUES('current') ON CONFLICT DO NOTHING")
    await conn.execute(
        "UPDATE system_settings SET embedding_fingerprint = $1 WHERE id='current'", stored
    )
    org = await OrganizationRepo(conn).create("Restored")
    return await WorkspaceRepo(conn).create(org.id, "Restored", "INTERNAL")


async def test_republishes_every_live_document_even_on_the_current_profile(conn, gateway) -> None:
    """Qdrant is empty after such a restore, so documents already on the gateway's
    fingerprint are re-published too (unlike an admin re-embed)."""
    ws = await _platform(conn)
    docs = DocumentRepo(conn)
    same = await docs.create(
        ws.id, "a.pdf", 1, "raggie_chunks_d1024", object_key="k/a", embedding_fingerprint="2872ae6a"
    )
    gone = await docs.create(
        ws.id, "b.pdf", 1, "raggie_chunks_d1024", object_key="k/b", embedding_fingerprint="2872ae6a"
    )
    await docs.soft_delete(gone.id)
    no_raw = await docs.create(
        ws.id, "c.pdf", 1, "raggie_chunks_d1024", embedding_fingerprint="2872ae6a"
    )
    publisher = RecordingPublisher()

    result = await reindex.reindex_all(conn, publisher, unknown_profile())

    assert result == {
        "reindexed": 1,
        "skipped": 1,
        "workspaces": result["workspaces"],
        "fingerprint": "2872ae6a",
        "collection": "raggie_chunks_d1024",
    }
    assert [p["document_id"] for _t, p in publisher.events] == [str(same.id)]
    assert (await docs.get(no_raw.id)).status == "PENDING"  # untouched, not re-armed
    started = await conn.fetchrow(
        "SELECT metadata FROM audit_log WHERE action = 'embedding.reembed_started'"
        " AND created_at >= now()"
    )
    assert started["metadata"]["trigger"] == "cli"


async def test_accepts_the_gateway_profile(conn, gateway) -> None:
    ws = await _platform(conn)
    await DocumentRepo(conn).create(
        ws.id, "a.pdf", 1, "raggie_chunks_d1024", object_key="k/a", embedding_fingerprint="2872ae6a"
    )
    gateway.routes["info"].respond(json=CLOUD_INFO)
    publisher = RecordingPublisher()

    result = await reindex.reindex_all(conn, publisher, unknown_profile())

    assert result["fingerprint"] == CLOUD_INFO["fingerprint"]
    assert (
        await conn.fetchval("SELECT embedding_fingerprint FROM system_settings WHERE id='current'")
        == CLOUD_INFO["fingerprint"]
    )
    assert {p["collection"] for _t, p in publisher.events} == {CLOUD_INFO["collection"]}


async def test_needs_the_gateway(conn, gateway) -> None:
    await _platform(conn)
    gateway.routes["info"].mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(GatewayUnavailableError):
        await reindex.reindex_all(conn, RecordingPublisher(), unknown_profile())


def test_cli_help() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "raggie_control_plane.reindex", "--help"],
        capture_output=True,
        text=True,
        timeout=60,
        env={"RAGGIE_ENV": "test", "PATH": "/usr/bin:/bin"},
        cwd=Path(__file__).resolve().parent.parent,
    )
    assert proc.returncode == 0 and "re-publish" in proc.stdout.lower()
