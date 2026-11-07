# SPDX-License-Identifier: Apache-2.0

"""Authorization matrix: every control-plane route x every principal.

The expected policy lives in ``authz_policy.yaml``. The suite fails when a route
has no policy entry (or an entry names a removed route), and — for each
principal — when an allowed caller is refused (401/403/404) or a denied caller
gets through. Two orgs are seeded once per principal; path params point at
org A, so ``super_admin_other_org`` proves tenant isolation. Every request runs
inside a savepoint that is rolled back, so mutating routes never affect the
next check.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import jwt
import pytest
import yaml
from embeddings_stub import LEGACY_INFO, known_profile
from fastapi import APIRouter, FastAPI
from fastapi.routing import iter_route_contexts
from httpx import ASGITransport

from raggie_control_plane.api import qdrant_viz, ratelimit
from raggie_control_plane.api.deps import (
    get_conn,
    get_embeddings_profile,
    get_event_publisher,
    get_object_store,
)
from raggie_control_plane.api.sso import get_oidc
from raggie_control_plane.auth.service import AuthService
from raggie_control_plane.config import settings
from raggie_control_plane.db.repositories import (
    AuthSessionRepo,
    DepartmentRepo,
    DocumentFolderRepo,
    DocumentRepo,
    IntegrationRepo,
    LocationRepo,
    MembershipRepo,
    OrganizationRepo,
    ScheduledTaskRepo,
    SkillsRepo,
    TeamRepo,
    UserRepo,
    WorkspaceRepo,
)
from raggie_control_plane.infra.objectstore import InMemoryObjectStore
from raggie_control_plane.main import app
from raggie_control_plane.security import decode_token, hash_password

POLICY = yaml.safe_load((Path(__file__).parent / "authz_policy.yaml").read_text())
PRINCIPALS = [
    "anonymous",
    "widget_token",
    "staff",
    "workspace_admin",
    "team_admin",
    "super_admin_same_org",
    "super_admin_other_org",
    "platform_admin",
    "deactivated_user",
    "revoked_token",
]
DENIED = {401, 403, 404}
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
_RealAsyncClient = httpx.AsyncClient

# Default fixture for each path parameter name (org A resources).
PATH_DEFAULTS = {
    "org_id": "org_a",
    "team_id": "team_a",
    "workspace_id": "ws_a",
    "user_id": "victim",
    "document_id": "doc_a",
    "folder_id": "folder_a",
    "dept_id": "dept_a",
    "loc_id": "loc_a",
    "invite_id": "invite_a",
    "token": "invite_raw",
    "integration_id": "integration_a",
    "notification_id": "notification_staff",
    "task_id": "task_staff",
    "skill_id": "org_skill",
    "version": "skill_version",
}


def _routes(application: FastAPI = app) -> set[str]:
    """Every served route, from the router itself rather than app.openapi(), so
    an include_in_schema=False route cannot escape the policy. FastAPI's own
    docs routes are excluded; a route without methods (websocket, mount) shows
    up as ANY so it still needs an entry."""
    docs = {application.openapi_url, application.docs_url, application.redoc_url}
    if application.docs_url:
        docs.add(application.swagger_ui_oauth2_redirect_url)
    out: set[str] = set()
    for route in iter_route_contexts(application.routes):
        path = route.path_format or route.path
        if path in docs:
            continue
        methods = set(route.methods or {"ANY"})
        if "GET" in methods:
            methods.discard("HEAD")  # Starlette's implicit HEAD mirrors GET
        out.update(f"{m} {path}" for m in methods)
    return out


def _allowed(entry: dict) -> set[str]:
    names = entry["allow"] if isinstance(entry["allow"], list) else [entry["allow"]]
    out: set[str] = set()
    for name in names:
        out.update(POLICY["groups"].get(name, [name]))
    unknown = out - set(PRINCIPALS)
    assert not unknown, f"unknown principals in policy: {unknown}"
    return out


def _route_key(key: str) -> str:
    """'METHOD /path#variant' -> 'METHOD /path' (variants are extra cases)."""
    return key.split("#", 1)[0]


def test_route_inventory_includes_routes_hidden_from_the_schema() -> None:
    hidden = APIRouter()

    @hidden.get("/hidden/{item_id}", include_in_schema=False)
    async def _hidden(item_id: str) -> None: ...

    probe = FastAPI(docs_url="/docs", redoc_url="/redoc")
    probe.include_router(hidden, prefix="/api")
    assert _routes(probe) == {"GET /api/hidden/{item_id}"}


def test_every_route_has_a_policy_entry() -> None:
    routes = _routes()
    policy = {_route_key(k) for k in POLICY["routes"]}
    assert not routes - policy, f"routes without a policy entry: {sorted(routes - policy)}"
    assert not policy - routes, f"policy entries for unknown routes: {sorted(policy - routes)}"


class _Publisher:
    async def publish(self, topic: str, payload: dict) -> str:
        return "0-0"


class _FakeOIDC:
    enabled = True

    def authorize_url(self, *, state: str, nonce: str, code_challenge: str) -> str:
        return "https://idp.example/authorize"

    async def exchange_code(self, code: str, *, code_verifier: str, nonce: str):
        raise AssertionError("never reached without the flow cookie")


def _widget_token() -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(uuid4()),
            "type": "access",
            "aud": "widget",
            "sid": str(uuid4()),
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )


async def _seed(conn) -> tuple[dict[str, str], dict[str, str]]:
    """Two tenants (+ the platform admin's own org). Returns (ids, bearer tokens)."""
    # Neutralize rows other suites may have committed to the shared database.
    await conn.execute("UPDATE users SET is_platform_admin = FALSE WHERE is_platform_admin")
    orgs, users, members = OrganizationRepo(conn), UserRepo(conn), MembershipRepo(conn)
    svc = AuthService(conn)
    org_a = await orgs.create("Matrix A")
    org_b = await orgs.create("Matrix B")
    org_p = await orgs.create("Matrix Platform")
    team_a = await TeamRepo(conn).create(org_a.id, "Team A")
    ws_a = await WorkspaceRepo(conn).create(org_a.id, "WS A", "INTERNAL", team_id=team_a.id)

    async def user(tag: str, role: str, org, **kw):
        return await users.create(
            f"{tag}-{uuid4().hex[:8]}@matrix.test", "h", role, org_id=org.id, **kw
        )

    staff = await user("staff", "STAFF", org_a)
    await members.add_workspace_member(ws_a.id, staff.id, "STAFF")
    ws_admin = await user("wsadmin", "WORKSPACE_ADMIN", org_a)
    await members.add_workspace_member(ws_a.id, ws_admin.id, "WORKSPACE_ADMIN")
    team_admin = await user("teamadmin", "WORKSPACE_ADMIN", org_a)
    await members.add_team_member(team_a.id, team_admin.id, "WORKSPACE_ADMIN")
    sa_a = await user("sa-a", "SUPER_ADMIN", org_a)
    sa_b = await user("sa-b", "SUPER_ADMIN", org_b)
    pa = await user("pa", "SUPER_ADMIN", org_p, is_platform_admin=True)
    deactivated = await user("gone", "STAFF", org_a)
    await members.add_workspace_member(ws_a.id, deactivated.id, "STAFF")
    revoked = await user("revoked", "STAFF", org_a)
    await members.add_workspace_member(ws_a.id, revoked.id, "STAFF")
    victim = await user("victim", "STAFF", org_a)
    await members.add_workspace_member(ws_a.id, victim.id, "STAFF")
    await members.add_team_member(team_a.id, victim.id, "STAFF")

    login_password = "matrix-login-password"
    login_user = await users.create(
        f"login-{uuid4().hex[:8]}@matrix.test",
        hash_password(login_password),
        "STAFF",
        org_id=org_a.id,
    )
    login_tokens = await svc.issue_tokens(login_user)

    tokens: dict[str, str] = {"widget_token": _widget_token()}
    for name, u in {
        "staff": staff,
        "workspace_admin": ws_admin,
        "team_admin": team_admin,
        "super_admin_same_org": sa_a,
        "super_admin_other_org": sa_b,
        "platform_admin": pa,
        "deactivated_user": deactivated,
        "revoked_token": revoked,
    }.items():
        tokens[name] = (await svc.issue_tokens(u)).access_token
    await users.set_active(deactivated.id, False)
    revoked_sid = decode_token(tokens["revoked_token"])["sid"]
    await AuthSessionRepo(conn).revoke(revoked_sid, revoked.id)

    doc = await DocumentRepo(conn).create(
        ws_a.id, "a.pdf", 1, "raggie_chunks_d1024", object_key=f"uploads/{ws_a.id}/a.pdf"
    )
    folder = await DocumentFolderRepo(conn).create(ws_a.id, "Folder A")
    dept = await DepartmentRepo(conn).create(org_a.id, "Dept A")
    loc = await LocationRepo(conn).create(org_a.id, "Loc A")
    invite, invite_raw = await svc.create_invite(
        org_a.id, "invitee@matrix.test", "STAFF", created_by=sa_a.id
    )
    integration = await IntegrationRepo(conn).upsert(
        org_id=org_a.id,
        scope_type="workspace",
        scope_id=ws_a.id,
        provider="slack",
        target_workspace_id=None,
        display_name="Slack",
        credentials_enc=None,
        config={},
        status="disconnected",
        created_by=ws_admin.id,
    )
    notification_id = await conn.fetchval(
        "INSERT INTO notifications (org_id, user_id, title, body) VALUES ($1, $2, 't', 'b')"
        " RETURNING id",
        org_a.id,
        staff.id,
    )
    task = await ScheduledTaskRepo(conn).create(
        org_a.id, staff.id, ws_a.id, name="t", prompt="p", cron="0 9 * * *"
    )
    skills = SkillsRepo(conn)
    org_skill = await skills.create(
        org_a.id, name="Org", slug=f"org-{uuid4().hex[:6]}", instructions="i", created_by=sa_a.id
    )
    personal = await skills.create_personal(
        org_a.id, staff.id, name="Mine", slug=f"mine-{uuid4().hex[:6]}", instructions="i"
    )

    ids = {
        "org_a": org_a.id,
        "org_b": org_b.id,
        "team_a": team_a.id,
        "ws_a": ws_a.id,
        "staff": staff.id,
        "victim": victim.id,
        "super_admin_same_org": sa_a.id,
        "doc_a": doc.id,
        "folder_a": folder.id,
        "dept_a": dept.id,
        "loc_a": loc.id,
        "invite_a": invite.id,
        "invite_raw": invite_raw,
        "integration_a": integration.id,
        "notification_staff": notification_id,
        "task_staff": task.id,
        "org_skill": org_skill.id,
        "personal_skill": personal.id,
        "skill_version": 1,
        "login_email": login_user.email,
        "login_password": login_password,
        "login_refresh": login_tokens.refresh_token,
    }
    return {k: str(v) for k, v in ids.items()}, tokens


def _fill(value: Any, ids: dict[str, str]) -> Any:
    if isinstance(value, str):
        return re.sub(r"\{(\w+)\}", lambda m: ids.get(m.group(1), m.group(0)), value)
    if isinstance(value, dict):
        return {k: _fill(v, ids) for k, v in value.items()}
    if isinstance(value, list):
        return [_fill(v, ids) for v in value]
    return value


def _url(path: str, entry: dict, ids: dict[str, str]) -> str:
    overrides = entry.get("params", {})

    def sub(m: re.Match) -> str:
        name = m.group(1)
        return ids[overrides.get(name, PATH_DEFAULTS[name])]

    return re.sub(r"\{(\w+)\}", sub, path)


@pytest.fixture
def isolated_app(conn, monkeypatch):
    """Route the app through the test connection and stub external systems."""
    monkeypatch.setattr(ratelimit, "_login_limiter", ratelimit.SlidingWindowLimiter(10**6, 60))
    monkeypatch.setattr(ratelimit, "_memory_lockout_store", ratelimit.MemoryLockoutStore())
    if hasattr(app.state, "redis"):
        monkeypatch.delattr(app.state, "redis")
    monkeypatch.setattr(settings, "scim_enabled", True)
    monkeypatch.setattr(settings, "scim_bearer_token", "matrix-scim-token-" + "x" * 20)
    monkeypatch.setattr(settings, "release_manifest_url", "")

    def fake_upstream(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/info"):  # embeddings gateway
            return httpx.Response(200, json=LEGACY_INFO)
        return httpx.Response(200, json={"result": {"points": []}})  # Qdrant

    def qdrant_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(fake_upstream)
        return _RealAsyncClient(*args, **kwargs)

    monkeypatch.setattr(qdrant_viz.httpx, "AsyncClient", qdrant_client)

    async def _conn_override():
        yield conn

    store = InMemoryObjectStore()
    profile = known_profile()
    app.dependency_overrides[get_conn] = _conn_override
    app.dependency_overrides[get_embeddings_profile] = lambda: profile
    app.dependency_overrides[get_object_store] = lambda: store
    app.dependency_overrides[get_event_publisher] = _Publisher
    app.dependency_overrides[get_oidc] = _FakeOIDC
    yield
    app.dependency_overrides.clear()


@pytest.mark.parametrize("principal", PRINCIPALS)
async def test_authz_matrix(principal, conn, isolated_app, monkeypatch) -> None:
    ids, tokens = await _seed(conn)
    monkeypatch.setattr(settings, "scim_org_id", ids["org_a"])
    headers = {"Authorization": f"Bearer {tokens[principal]}"} if principal in tokens else {}
    mismatches: list[str] = []
    async with _RealAsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", headers=headers
    ) as client:
        for key, entry in sorted(POLICY["routes"].items()):
            method, path = _route_key(key).split(" ", 1)
            request: dict[str, Any] = {"params": _fill(entry.get("query"), ids)}
            if "json" in entry:
                request["json"] = _fill(entry["json"], ids)
            if entry.get("file") == "png":
                request["files"] = {"file": ("x.png", PNG, "image/png")}
            elif entry.get("file") == "txt":
                request["files"] = {"file": ("x.txt", b"hello", "text/plain")}
            if "headers" in entry:
                request["headers"] = _fill(entry["headers"], ids)
                request["content"] = b"x"
            savepoint = conn.transaction()
            await savepoint.start()
            try:
                r = await client.request(method, _url(path, entry, ids), **request)
            finally:
                await savepoint.rollback()
            should_allow = principal in _allowed(entry)
            if should_allow:
                ok = r.status_code not in DENIED and (
                    r.status_code < 500 or entry.get("allow_5xx", False)
                )
            else:
                ok = r.status_code in DENIED
            if not ok:
                verdict = "allowed" if should_allow else "denied"
                mismatches.append(f"{key}: expected {verdict}, got {r.status_code} {r.text[:120]}")
    assert not mismatches, f"{principal}:\n" + "\n".join(mismatches)
