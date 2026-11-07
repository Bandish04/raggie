# SPDX-License-Identifier: Apache-2.0

from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from embeddings_stub import known_profile
from httpx import ASGITransport

from raggie_control_plane.api.deps import (
    get_conn,
    get_current_user,
    get_embeddings_profile,
    get_event_publisher,
    get_object_store,
)
from raggie_control_plane.config import settings
from raggie_control_plane.db.repositories import DocumentRepo, OrganizationRepo, WorkspaceRepo
from raggie_control_plane.infra.objectstore import InMemoryObjectStore
from raggie_control_plane.main import app
from raggie_control_plane.models import Role, User


class RecordingPublisher:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def publish(self, topic: str, payload: dict) -> str:
        self.events.append((topic, payload))
        return "1-0"


@pytest_asyncio.fixture
async def doc_client(conn):
    su = User(
        id=uuid4(),
        org_id=None,
        email="su@raggie.test",
        role=Role.SUPER_ADMIN,
        is_platform_admin=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    store = InMemoryObjectStore()
    publisher = RecordingPublisher()

    async def _conn_override():
        yield conn

    app.dependency_overrides[get_conn] = _conn_override
    app.dependency_overrides[get_current_user] = lambda: su
    app.dependency_overrides[get_object_store] = lambda: store
    app.dependency_overrides[get_event_publisher] = lambda: publisher
    profile = known_profile()
    app.dependency_overrides[get_embeddings_profile] = lambda: profile
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, store, publisher
    app.dependency_overrides.clear()


async def test_upload_creates_pending_and_publishes(doc_client, conn) -> None:
    client, store, publisher = doc_client
    org = await OrganizationRepo(conn).create("Acme")
    ws = await WorkspaceRepo(conn).create(org.id, "Docs", "INTERNAL")

    files = {"file": ("notes.txt", b"hello world", "text/plain")}
    r = await client.post(f"/api/v1/admin/workspaces/{ws.id}/documents", files=files)
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "PENDING"
    assert body["qdrant_collection_name"] == "raggie_chunks_d1024"

    # Raw file landed in the object store.
    assert await store.get(body["object_key"]) == b"hello world"

    # document.uploaded event published with the matching contract payload.
    assert publisher.events
    topic, payload = publisher.events[0]
    assert topic == "raggie.document.uploaded"
    assert payload["document_id"] == body["id"]
    assert payload["embedding_dim"] == 1024


async def test_direct_upload_uses_safe_unique_object_key(doc_client, conn) -> None:
    client, _store, _publisher = doc_client
    org = await OrganizationRepo(conn).create("Acme")
    ws = await WorkspaceRepo(conn).create(org.id, "Docs", "INTERNAL")

    r = await client.post(
        f"/api/v1/admin/workspaces/{ws.id}/documents",
        files={"file": ("../../notes.txt", b"hello", "text/plain")},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["filename"] == "notes.txt"
    assert body["object_key"].startswith(f"uploads/{ws.id}/")
    assert ".." not in body["object_key"]


async def test_direct_upload_rejects_unsupported_and_oversized_files(
    doc_client, conn, monkeypatch
) -> None:
    client, _store, _publisher = doc_client
    org = await OrganizationRepo(conn).create("Acme")
    ws = await WorkspaceRepo(conn).create(org.id, "Docs", "INTERNAL")

    unsupported = await client.post(
        f"/api/v1/admin/workspaces/{ws.id}/documents",
        files={"file": ("payload.html", b"<script></script>", "text/html")},
    )
    assert unsupported.status_code == 415

    monkeypatch.setattr(settings, "direct_upload_max_bytes", 3)
    oversized = await client.post(
        f"/api/v1/admin/workspaces/{ws.id}/documents",
        files={"file": ("large.txt", b"1234", "text/plain")},
    )
    assert oversized.status_code == 413


@pytest.mark.parametrize(
    ("filename", "content_type"),
    [
        ("finance.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        (
            "roadmap.pptx",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ),
    ],
)
async def test_direct_upload_accepts_office_formats(
    doc_client, conn, filename, content_type
) -> None:
    client, _store, _publisher = doc_client
    org = await OrganizationRepo(conn).create(f"Acme {filename}")
    ws = await WorkspaceRepo(conn).create(org.id, "Docs", "INTERNAL")
    response = await client.post(
        f"/api/v1/admin/workspaces/{ws.id}/documents",
        files={"file": (filename, b"PK-test-fixture", content_type)},
    )
    assert response.status_code == 201
    assert response.json()["filename"] == filename


async def test_multipart_limits_parts_and_removes_oversized_final_object(
    doc_client, conn, monkeypatch
) -> None:
    client, store, _publisher = doc_client
    org = await OrganizationRepo(conn).create("Acme")
    ws = await WorkspaceRepo(conn).create(org.id, "Docs", "INTERNAL")
    base = f"/api/v1/admin/workspaces/{ws.id}/documents/uploads"

    monkeypatch.setattr(settings, "upload_part_size", 3)
    created = await client.post(
        base,
        json={"filename": "large.txt", "content_type": "text/plain"},
    )
    assert created.status_code == 200
    upload = created.json()
    headers = {
        "X-Upload-Id": upload["upload_id"],
        "X-Object-Key": upload["object_key"],
        "X-Part-Number": "1",
    }
    assert (await client.put(f"{base}/parts", headers=headers, content=b"1234")).status_code == 413

    monkeypatch.setattr(settings, "upload_part_size", 10)
    part = await client.put(f"{base}/parts", headers=headers, content=b"1234")
    assert part.status_code == 200
    monkeypatch.setattr(settings, "max_upload_bytes", 3)
    completed = await client.post(
        f"{base}/complete",
        json={
            "upload_id": upload["upload_id"],
            "object_key": upload["object_key"],
            "filename": "large.txt",
            "parts": [part.json()],
        },
    )
    assert completed.status_code == 413
    with pytest.raises(KeyError):
        await store.get(upload["object_key"])


async def test_list_documents(doc_client, conn) -> None:
    client, _store, _publisher = doc_client
    org = await OrganizationRepo(conn).create("Acme")
    ws = await WorkspaceRepo(conn).create(org.id, "Docs", "INTERNAL")
    await client.post(
        f"/api/v1/admin/workspaces/{ws.id}/documents",
        files={"file": ("a.txt", b"x", "text/plain")},
    )
    r = await client.get(f"/api/v1/admin/workspaces/{ws.id}/documents")
    assert r.status_code == 200
    assert len(r.json()) == 1


async def test_reindex_skips_archived_and_deleted_documents(doc_client, conn) -> None:
    client, _store, publisher = doc_client
    org = await OrganizationRepo(conn).create("Acme")
    ws = await WorkspaceRepo(conn).create(org.id, "Docs", "INTERNAL")
    docs = DocumentRepo(conn)
    live = await docs.create(ws.id, "live.pdf", 1, "raggie_chunks_d1024", object_key="k/live")
    archived = await docs.create(ws.id, "old.pdf", 1, "raggie_chunks_d1024", object_key="k/old")
    gone = await docs.create(ws.id, "gone.pdf", 1, "raggie_chunks_d1024", object_key="k/gone")
    await docs.archive(archived.id)
    await docs.soft_delete(gone.id)

    r = await client.post(f"/api/v1/admin/workspaces/{ws.id}/documents/reindex")
    assert r.status_code == 200 and r.json() == {"reindexed": 1, "skipped": 0}
    assert [p["document_id"] for _t, p in publisher.events] == [str(live.id)]
    # The archived document stays archived (not re-armed into retrieval).
    assert (await docs.get(archived.id)).status == "ARCHIVED"


async def test_delete_document_soft_deletes_purges_and_hides_it(doc_client, conn) -> None:
    client, _store, publisher = doc_client
    org = await OrganizationRepo(conn).create("Acme")
    ws = await WorkspaceRepo(conn).create(org.id, "Docs", "INTERNAL")
    docs = DocumentRepo(conn)
    keep = await docs.create(ws.id, "keep.pdf", 1, "raggie_chunks_d1024", object_key="k/keep")
    gone = await docs.create(ws.id, "gone.pdf", 1, "raggie_chunks_d1024", object_key="k/gone")
    url = f"/api/v1/admin/workspaces/{ws.id}/documents/{gone.id}"

    r = await client.delete(url)
    assert r.status_code == 204
    # Soft delete: the row stays (deleted_at set) for the cascade and audit.
    deleted_at = await conn.fetchval("SELECT deleted_at FROM documents WHERE id = $1", gone.id)
    assert deleted_at is not None
    # The hard-purge cascade: Qdrant chunks AND the raw object.
    assert publisher.events == [
        (
            "raggie.document.deleted",
            {
                "document_id": str(gone.id),
                "workspace_id": str(ws.id),
                "object_key": "k/gone",
                "collection": "raggie_chunks_d1024",
                "purge_object": True,
            },
        )
    ]
    # Listings no longer show it, with or without a folder filter.
    base = f"/api/v1/admin/workspaces/{ws.id}/documents"
    for params in ({}, {"folder_id": "root"}):
        listed = await client.get(base, params=params)
        assert [d["id"] for d in listed.json()] == [str(keep.id)]
    # A second delete finds nothing and publishes nothing.
    assert (await client.delete(url)).status_code == 404
    assert len(publisher.events) == 1


async def test_delete_document_of_another_workspace_is_404(doc_client, conn) -> None:
    client, _store, publisher = doc_client
    org = await OrganizationRepo(conn).create("Acme")
    ws = await WorkspaceRepo(conn).create(org.id, "Docs", "INTERNAL")
    other = await WorkspaceRepo(conn).create(org.id, "Other", "INTERNAL")
    doc = await DocumentRepo(conn).create(other.id, "x.pdf", 1, "raggie_chunks_d1024")

    r = await client.delete(f"/api/v1/admin/workspaces/{ws.id}/documents/{doc.id}")
    assert r.status_code == 404
    assert await DocumentRepo(conn).get(doc.id) is not None
    assert publisher.events == []
