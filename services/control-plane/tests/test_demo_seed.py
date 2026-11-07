# SPDX-License-Identifier: Apache-2.0

"""Demo seeder: org, teams, workspaces, users and corpus upload (no ingestion)."""

import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from embeddings_stub import CLOUD_INFO, unknown_profile

from raggie_control_plane import demo
from raggie_control_plane.db.repositories import (
    DocumentRepo,
    OrganizationRepo,
    TeamRepo,
    UserRepo,
    WorkspaceRepo,
)
from raggie_control_plane.embeddings_profile import IngestTarget
from raggie_control_plane.infra.objectstore import InMemoryObjectStore
from raggie_control_plane.security import verify_password

ORG = "Nebula Teknoloji (demo test)"


class RecordingPublisher:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def publish(self, topic: str, payload: dict) -> str:
        self.events.append((topic, payload))
        return "1-0"


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    (tmp_path / "finans").mkdir()
    (tmp_path / "finans" / "Butce_2026.md").write_text("# Bütçe", encoding="utf-8")
    (tmp_path / "finans" / "Rapor.pdf").write_bytes(b"%PDF-1.4 demo")
    (tmp_path / "arge").mkdir()
    (tmp_path / "arge" / "Mimari.txt").write_text("mimari", encoding="utf-8")
    (tmp_path / "arge" / "notes.exe").write_bytes(b"MZ")  # unsupported: skipped
    (tmp_path / "arge" / "README.md").write_text("folder notes", encoding="utf-8")  # skipped
    (tmp_path / "ceo-ofisi").mkdir()
    (tmp_path / "ceo-ofisi" / "Genelge.png").write_bytes(b"\x89PNG\r\n\x1a\n")  # OCR'd
    (tmp_path / "README.md").write_text("corpus readme", encoding="utf-8")
    return tmp_path


async def _seed(conn, corpus, store=None, publisher=None):
    return await demo.seed_demo(
        conn,
        corpus=corpus,
        org_name=ORG,
        store=store or InMemoryObjectStore(),
        publisher=publisher or RecordingPublisher(),
        target=IngestTarget("raggie_chunks_d1024", "2872ae6a", 1024),
    )


async def test_seed_creates_tenant_users_and_uploads(conn, corpus) -> None:
    store, publisher = InMemoryObjectStore(), RecordingPublisher()
    result = await _seed(conn, corpus, store, publisher)

    orgs = [o for o in await OrganizationRepo(conn).list() if o.name == ORG]
    assert len(orgs) == 1
    org_id = orgs[0].id
    teams = await TeamRepo(conn).list_by_org(org_id)
    assert len(teams) == len(demo.DEPARTMENTS)
    workspaces = {w.name: w for w in await WorkspaceRepo(conn).list_by_org(org_id)}
    assert demo.GENERAL_WORKSPACE in workspaces
    assert len(workspaces) == len(demo.DEPARTMENTS) + 1

    users = await UserRepo(conn).list(org_id=org_id, limit=500)
    expected_users = 1 + sum(1 + len(d.staff) for d in demo.DEPARTMENTS)
    assert len(users) == expected_users
    assert all(u.email.endswith("@nebulacrm.example") for u in users)
    # Strong, unique, generated passwords — returned once, stored only hashed.
    assert len(result.credentials) == expected_users
    passwords = [pw for _email, pw in result.credentials]
    assert len(set(passwords)) == len(passwords) and min(map(len, passwords)) >= 20
    email, pw = result.credentials[0]
    pw_hash = await UserRepo(conn).get_password_hash(email)
    assert pw_hash and verify_password(pw_hash, pw)

    finans = workspaces["Finans"]
    finans_docs = {d.filename for d in await DocumentRepo(conn).list_by_workspace(finans.id)}
    assert finans_docs == {"Butce_2026.md", "Rapor.pdf"}
    general = workspaces[demo.GENERAL_WORKSPACE]
    general_docs = {d.filename for d in await DocumentRepo(conn).list_by_workspace(general.id)}
    assert general_docs == {"Butce_2026.md", "Rapor.pdf", "Mimari.txt", "Genelge.png"}
    ceo = workspaces["CEO Ofisi"]
    assert {d.filename for d in await DocumentRepo(conn).list_by_workspace(ceo.id)} == {
        "Genelge.png"
    }
    # Uploaded through the normal intake path: raw object stored + event published
    # (4 department uploads + the same 4 into the company-wide workspace).
    assert len(publisher.events) == 8 == result.documents_uploaded
    assert all(topic == "raggie.document.uploaded" for topic, _p in publisher.events)
    for _topic, payload in publisher.events:
        assert await store.get(payload["object_key"])


async def test_seed_is_idempotent(conn, corpus) -> None:
    publisher = RecordingPublisher()
    await _seed(conn, corpus, publisher=publisher)
    first_events = len(publisher.events)
    again = await _seed(conn, corpus, publisher=publisher)
    assert again.credentials == []  # nobody new; existing passwords untouched
    assert again.documents_uploaded == 0 and len(publisher.events) == first_events
    assert len([o for o in await OrganizationRepo(conn).list() if o.name == ORG]) == 1


async def test_seed_refuses_to_adopt_users_from_another_org(conn, corpus) -> None:
    other = await OrganizationRepo(conn).create("Someone Else")
    clash = demo.DEPARTMENTS[0].head.email
    await UserRepo(conn).create(clash, "h", "STAFF", org_id=other.id)
    with pytest.raises(demo.DemoSeedError, match="another organization"):
        await _seed(conn, corpus)


async def test_seed_requires_existing_corpus(conn, tmp_path) -> None:
    with pytest.raises(demo.DemoSeedError, match="corpus"):
        await _seed(conn, tmp_path / "missing")


def test_no_real_domains_in_demo_data() -> None:
    source = Path(demo.__file__).read_text(encoding="utf-8")
    assert "nebulacrm.com" not in source
    assert all(p.email.endswith("@nebulacrm.example") for p in demo.all_people())


def test_cli_help() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "raggie_control_plane.demo", "seed", "--help"],
        capture_output=True,
        text=True,
        timeout=60,
        env={"RAGGIE_ENV": "test", "PATH": "/usr/bin:/bin"},
        cwd=Path(__file__).resolve().parent.parent,
    )
    assert proc.returncode == 0 and "--corpus" in proc.stdout and "--password-file" in proc.stdout


async def test_seed_targets_the_gateway_collection(conn, corpus) -> None:
    publisher = RecordingPublisher()
    await _seed(conn, corpus, publisher=publisher)
    assert {p["collection"] for _t, p in publisher.events} == {"raggie_chunks_d1024"}
    assert {p["embedding_fingerprint"] for _t, p in publisher.events} == {"2872ae6a"}


async def test_resolve_target_refuses_on_a_profile_mismatch(conn, gateway) -> None:
    await conn.execute("UPDATE documents SET deleted_at = now() WHERE deleted_at IS NULL")
    await conn.execute(
        "UPDATE system_settings SET embedding_fingerprint = '2872ae6a' WHERE id='current'"
    )
    org = await OrganizationRepo(conn).create("Indexed")
    ws = await WorkspaceRepo(conn).create(org.id, "Indexed", "INTERNAL")
    await DocumentRepo(conn).create(
        ws.id, "a.pdf", 1, "raggie_chunks_d1024", embedding_fingerprint="2872ae6a"
    )
    gateway.routes["info"].respond(json=CLOUD_INFO)
    with pytest.raises(demo.DemoSeedError, match="re-embedded"):
        await demo.resolve_ingest_target(conn, RecordingPublisher(), unknown_profile())


async def test_resolve_target_refuses_without_a_gateway(conn, gateway) -> None:
    gateway.routes["info"].mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(demo.DemoSeedError, match="embeddings service"):
        await demo.resolve_ingest_target(conn, RecordingPublisher(), unknown_profile())


_SAMPLE_CORPUS = Path(__file__).resolve().parents[3] / demo.DEFAULT_CORPUS


@pytest.mark.skipif(not _SAMPLE_CORPUS.is_dir(), reason="sample corpus not in this checkout")
def test_sample_corpus_maps_onto_the_demo_departments() -> None:
    """Every corpus folder is a department's workspace, and every document in it
    is accepted by the upload route (the PNG goes through OCR)."""
    folders = {p.name for p in _SAMPLE_CORPUS.iterdir() if p.is_dir()}
    assert folders == {d.folder for d in demo.DEPARTMENTS}
    files = [f for d in demo.DEPARTMENTS for f in demo._corpus_files(_SAMPLE_CORPUS / d.folder)]
    assert all(demo._validated_filename(f.name) == f.name for f in files)
    assert len(files) == 39
    assert any(f.suffix == ".png" for f in files)
