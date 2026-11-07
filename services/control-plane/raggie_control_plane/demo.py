# SPDX-License-Identifier: Apache-2.0

"""Demo tenant seeder for the synthetic "Nebula Teknoloji" sample corpus.

    python -m raggie_control_plane.demo seed --corpus examples/sample-corpus \\
        [--org "Nebula Teknoloji (demo)"] [--password-file creds.tsv]

Creates (idempotently) a demo organization with one team + workspace per
department, a company-wide workspace, a location, departments and a ~30-person
org chart, then uploads the corpus through the normal document intake path so
the ingestion workers index it. Every person uses the reserved ``.example``
domain. New users get a strong random password that is shown exactly once
(stdout, or the ``--password-file`` written with mode 0600); re-running never
changes an existing user, workspace or document.

Run it against a migrated database with the stack's Redis/MinIO reachable (the
same settings as the control plane). The names and titles are Turkish because
the corpus is.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import secrets
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import asyncpg
from fastapi import HTTPException

from raggie_control_plane.api.documents import _validated_filename, ingest_document
from raggie_control_plane.db.repositories import (
    DepartmentRepo,
    DocumentRepo,
    LocationRepo,
    MembershipRepo,
    OrganizationRepo,
    TeamRepo,
    UserRepo,
    WorkspaceRepo,
)
from raggie_control_plane.embeddings_profile import (
    EmbeddingsProfile,
    GatewayUnavailableError,
    IngestBlockedError,
    IngestTarget,
)
from raggie_control_plane.infra.objectstore import ObjectStore
from raggie_control_plane.infra.publisher import EventPublisher
from raggie_control_plane.models import Workspace
from raggie_control_plane.security import hash_password

DEFAULT_ORG = "Nebula Teknoloji (demo)"
DEFAULT_CORPUS = "examples/sample-corpus"
GENERAL_WORKSPACE = "Tüm Şirket"
EMAIL_DOMAIN = "nebulacrm.example"  # RFC 2606 reserved: never a real mailbox
# Corpus files that are documentation of the corpus, not company documents.
_SKIP_FILES = {"README.md"}

_ASCII = str.maketrans(
    {
        "ç": "c",
        "ş": "s",
        "ğ": "g",
        "ı": "i",
        "ö": "o",
        "ü": "u",
        "Ç": "c",
        "Ş": "s",
        "Ğ": "g",
        "İ": "i",
        "Ö": "o",
        "Ü": "u",
    }
)


@dataclass(frozen=True)
class Person:
    name: str
    title: str

    @property
    def email(self) -> str:
        parts = self.name.translate(_ASCII).lower().split()
        return f"{parts[0]}.{parts[-1]}@{EMAIL_DOMAIN}"


@dataclass(frozen=True)
class Department:
    folder: str  # corpus sub-directory holding this department's documents
    name: str
    head: Person
    staff: tuple[Person, ...]


CEO = Person("Mehmet Yılmaz", "CEO")
DEPARTMENTS: tuple[Department, ...] = (
    Department(
        "arge",
        "Ar-Ge",
        Person("Ayşe Demir", "Ar-Ge Müdürü"),
        (Person("Okan Yıldız", "Kıdemli Yazılım Mühendisi"), Person("Gizem Aksoy", "Veri Bilimci")),
    ),
    Department(
        "bilgi-teknolojileri",
        "Bilgi Teknolojileri",
        Person("Emre Kaya", "BT Müdürü"),
        (Person("Murat Şen", "Sistem Yöneticisi"), Person("Ece Polat", "DevOps Mühendisi")),
    ),
    Department(
        "ceo-ofisi",
        "CEO Ofisi",
        Person("Zeynep Şahin", "CEO Ofisi Müdürü"),
        (Person("Kerem Acar", "İcra Asistanı"),),
    ),
    Department(
        "finans",
        "Finans",
        Person("Ali Vural", "Finans Müdürü"),
        (Person("Buse Erdoğan", "Mali Müşavir"), Person("Tolga Yıldırım", "Finans Analisti")),
    ),
    Department(
        "hukuk-uyum",
        "Hukuk ve Uyum",
        Person("Elif Aydın", "Hukuk ve Uyum Müdürü"),
        (Person("Naz Kurt", "Hukuk Müşaviri"), Person("Onur Aslan", "Uyum Uzmanı")),
    ),
    Department(
        "insan-kaynaklari",
        "İnsan Kaynakları",
        Person("Burak Çelik", "İnsan Kaynakları Müdürü"),
        (Person("Sıla Çetin", "İK Uzmanı"), Person("Berk Güneş", "İşe Alım Uzmanı")),
    ),
    Department(
        "kalite-yonetimi",
        "Kalite Yönetimi",
        Person("Selin Arslan", "Kalite Müdürü"),
        (Person("Pınar Yalçın", "Kalite Uzmanı"), Person("Hakan Bulut", "Test Mühendisi")),
    ),
    Department(
        "musteri-deneyimi",
        "Müşteri Deneyimi",
        Person("Can Öztürk", "Müşteri Deneyimi Müdürü"),
        (Person("Derya Kılıç", "Destek Uzmanı"), Person("Efe Taş", "Müşteri Başarı Uzmanı")),
    ),
    Department(
        "pazarlama-satis",
        "Pazarlama ve Satış",
        Person("Deniz Koç", "Pazarlama ve Satış Müdürü"),
        (Person("Cansu Aydın", "Pazarlama Uzmanı"), Person("Mert Özdemir", "Satış Temsilcisi")),
    ),
    Department(
        "urun-yonetimi",
        "Ürün Yönetimi",
        Person("Merve Doğan", "Ürün Müdürü"),
        (Person("İrem Korkmaz", "Ürün Sahibi"), Person("Yusuf Eren", "UX Tasarımcısı")),
    ),
)


def all_people() -> Iterator[Person]:
    yield CEO
    for dept in DEPARTMENTS:
        yield dept.head
        yield from dept.staff


class DemoSeedError(RuntimeError):
    """The demo cannot be seeded safely (message is operator-facing)."""


@dataclass
class SeedResult:
    org_id: str
    credentials: list[tuple[str, str]] = field(default_factory=list)  # new users only
    documents_uploaded: int = 0


def _new_password() -> str:
    return secrets.token_urlsafe(18)  # 24 chars, ~144 bits


class _Seeder:
    def __init__(
        self,
        conn: asyncpg.Connection,
        store: ObjectStore,
        publisher: EventPublisher,
        target: IngestTarget,
    ) -> None:
        self.conn = conn
        self.store = store
        self.publisher = publisher
        self.target = target
        self.result = SeedResult(org_id="")

    async def org(self, name: str):
        for org in await OrganizationRepo(self.conn).list():
            if org.name == name:
                return org
        return await OrganizationRepo(self.conn).create(name)

    async def user(self, org_id, person: Person, role: str, **profile):
        repo = UserRepo(self.conn)
        existing = await repo.get_by_email(person.email)
        if existing is not None:
            if existing.org_id != org_id:
                raise DemoSeedError(
                    f"{person.email} already belongs to another organization; refusing to adopt it"
                )
            return existing
        password = _new_password()
        user = await repo.create(
            person.email,
            hash_password(password),
            role,
            org_id=org_id,
            full_name=person.name,
            job_title=person.title,
            **profile,
        )
        self.result.credentials.append((person.email, password))
        return user

    async def workspace(self, org_id, name: str, team_id=None) -> Workspace:
        for ws in await WorkspaceRepo(self.conn).list_by_org(org_id):
            if ws.name == name:
                return ws
        return await WorkspaceRepo(self.conn).create(org_id, name, "INTERNAL", team_id=team_id)

    async def upload_folder(self, workspace: Workspace, files: list[Path]) -> None:
        existing = await DocumentRepo(self.conn).list_by_workspace(workspace.id)
        present = {d.filename for d in existing}
        for path in files:
            try:
                filename = _validated_filename(path.name)
            except HTTPException:
                continue  # unsupported type: the upload route would refuse it too
            if filename in present:
                continue
            await ingest_document(
                self.conn,
                self.store,
                self.publisher,
                workspace,
                filename,
                path.read_bytes(),
                target=self.target,
            )
            present.add(filename)
            self.result.documents_uploaded += 1


def _corpus_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.iterdir() if p.is_file() and p.name not in _SKIP_FILES)


async def seed_demo(
    conn: asyncpg.Connection,
    *,
    corpus: Path,
    org_name: str = DEFAULT_ORG,
    store: ObjectStore,
    publisher: EventPublisher,
    target: IngestTarget,
) -> SeedResult:
    """``target`` is the embedding profile's collection + fingerprint
    (resolve_ingest_target)."""
    if not corpus.is_dir():
        raise DemoSeedError(f"corpus directory not found: {corpus}")
    s = _Seeder(conn, store, publisher, target)
    members = MembershipRepo(conn)
    async with conn.transaction():
        org = await s.org(org_name)
        s.result.org_id = str(org.id)
        locations = {loc.name: loc for loc in await LocationRepo(conn).list_by_org(org.id)}
        location = locations.get("Genel Merkez") or await LocationRepo(conn).create(
            org.id, "Genel Merkez", city="İstanbul", country="Türkiye"
        )
        departments = {d.name: d for d in await DepartmentRepo(conn).list_by_org(org.id)}
        teams = {t.name: t for t in await TeamRepo(conn).list_by_org(org.id)}

        ceo_dept = departments.get("CEO Ofisi") or await DepartmentRepo(conn).create(
            org.id, "CEO Ofisi"
        )
        departments["CEO Ofisi"] = ceo_dept
        ceo = await s.user(
            org.id,
            CEO,
            "WORKSPACE_ADMIN",
            department="CEO Ofisi",
            department_id=ceo_dept.id,
            location="Genel Merkez",
            location_id=location.id,
        )
        general = await s.workspace(org.id, GENERAL_WORKSPACE)
        await members.add_workspace_member(general.id, ceo.id, "WORKSPACE_ADMIN")

        dept_workspaces: list[tuple[Department, Workspace]] = []
        for dept in DEPARTMENTS:
            department = departments.get(dept.name) or await DepartmentRepo(conn).create(
                org.id, dept.name
            )
            team = teams.get(dept.name) or await TeamRepo(conn).create(org.id, dept.name)
            workspace = await s.workspace(org.id, dept.name, team_id=team.id)
            profile = {
                "department": dept.name,
                "department_id": department.id,
                "location": "Genel Merkez",
                "location_id": location.id,
            }
            head = await s.user(
                org.id, dept.head, "WORKSPACE_ADMIN", manager_user_id=ceo.id, **profile
            )
            if department.owner_user_id is None:
                await DepartmentRepo(conn).update(department.id, owner_user_id=head.id)
            # Team membership grants the department workspace (team closure).
            await members.add_team_member(team.id, head.id, "WORKSPACE_ADMIN")
            await members.add_workspace_member(general.id, head.id, "STAFF")
            for person in dept.staff:
                staff = await s.user(org.id, person, "STAFF", manager_user_id=head.id, **profile)
                await members.add_team_member(team.id, staff.id, "STAFF")
                await members.add_workspace_member(general.id, staff.id, "STAFF")
            dept_workspaces.append((dept, workspace))

        everything: list[Path] = []
        for dept, workspace in dept_workspaces:
            files = _corpus_files(corpus / dept.folder)
            await s.upload_folder(workspace, files)
            everything.extend(files)
        await s.upload_folder(general, everything)
    return s.result


async def resolve_ingest_target(
    conn: asyncpg.Connection, publisher: EventPublisher, profile: EmbeddingsProfile
) -> IngestTarget:
    """Reconcile with the embeddings gateway exactly like a control-plane boot and
    return where uploads go, or refuse (gateway down / profile mismatch)."""
    try:
        await profile.reconcile(conn, publisher)
        return await profile.ingest_target(conn)
    except GatewayUnavailableError as exc:
        raise DemoSeedError(f"{exc}; start the embeddings service first") from exc
    except IngestBlockedError as exc:
        raise DemoSeedError(exc.detail) from exc


# ── CLI ──────────────────────────────────────────────────────────────────────
def _write_credentials(result: SeedResult, password_file: str | None) -> None:
    if not result.credentials:
        print("No new users were created; existing passwords are unchanged.")
        return
    lines = [f"{email}\t{password}" for email, password in result.credentials]
    if password_file:
        fd = os.open(password_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        print(f"Wrote {len(lines)} new demo credentials to {password_file} (mode 0600).")
        return
    print("New demo users (passwords are shown ONCE, store them now):")
    for line in lines:
        print(f"  {line}")


async def _run_seed(args: argparse.Namespace) -> int:
    from raggie_control_plane.config import settings
    from raggie_control_plane.db.migrate import pending_migrations
    from raggie_control_plane.db.pool import create_pool
    from raggie_control_plane.infra.objectstore import MinioObjectStore
    from raggie_control_plane.infra.publisher import RedisEventPublisher
    from raggie_control_plane.infra.redisconn import create_redis

    pool = await create_pool()
    redis_conn = create_redis(settings)
    store = MinioObjectStore(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_root_user,
        secret_key=settings.minio_root_password,
        bucket=settings.minio_bucket,
        secure=settings.minio_use_ssl,
    )
    try:
        async with pool.acquire() as conn:
            if await pending_migrations(conn, settings.migrations_dir):
                print(
                    "demo: database schema is behind; run "
                    "`python -m raggie_control_plane.db.migrate` first",
                    file=sys.stderr,
                )
                return 1
            publisher = RedisEventPublisher(redis_conn.client)
            target = await resolve_ingest_target(
                conn, publisher, EmbeddingsProfile.from_settings(settings)
            )
            result = await seed_demo(
                conn,
                corpus=Path(args.corpus),
                org_name=args.org,
                store=store,
                publisher=publisher,
                target=target,
            )
    except DemoSeedError as exc:
        print(f"demo: {exc}", file=sys.stderr)
        return 1
    finally:
        await redis_conn.aclose()
        await pool.close()
    print(
        f"Demo organization {args.org!r} ({result.org_id}) is ready; "
        f"{result.documents_uploaded} document(s) queued for ingestion."
    )
    _write_credentials(result, args.password_file)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m raggie_control_plane.demo")
    sub = parser.add_subparsers(dest="command", required=True)
    seed = sub.add_parser("seed", help="create the demo tenant and upload the sample corpus")
    seed.add_argument(
        "--corpus", default=DEFAULT_CORPUS, help=f"corpus directory (default: {DEFAULT_CORPUS})"
    )
    seed.add_argument(
        "--org", default=DEFAULT_ORG, help=f"demo organization name (default: {DEFAULT_ORG!r})"
    )
    seed.add_argument(
        "--password-file", help="write new users' credentials here (0600) instead of stdout"
    )
    args = parser.parse_args(argv)
    return asyncio.run(_run_seed(args))


if __name__ == "__main__":
    sys.exit(main())
