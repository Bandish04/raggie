# SPDX-License-Identifier: Apache-2.0

import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport

from raggie_control_plane.api import scim as scim_api
from raggie_control_plane.api.deps import get_conn
from raggie_control_plane.api.sso import get_oidc
from raggie_control_plane.auth.oidc import OIDCClaims, OIDCClient, OIDCError
from raggie_control_plane.config import settings
from raggie_control_plane.db.repositories import OrganizationRepo, UserRepo
from raggie_control_plane.main import app

ISSUER = "https://idp.example"


class FakeOIDC:
    """Records what the callback forwards so PKCE/nonce binding can be asserted."""

    enabled = True

    def __init__(self, claims: OIDCClaims | None = None) -> None:
        self.claims = claims or OIDCClaims(
            subject="idp-sub-123",
            email="alice@corp.example",
            email_verified=True,
            issuer=ISSUER,
        )
        self.exchanged: dict = {}

    def authorize_url(self, *, state: str, nonce: str, code_challenge: str) -> str:
        q = f"state={state}&nonce={nonce}&code_challenge={code_challenge}"
        return f"{ISSUER}/authorize?{q}&code_challenge_method=S256"

    async def exchange_code(self, code: str, *, code_verifier: str, nonce: str) -> OIDCClaims:
        self.exchanged = {"code": code, "code_verifier": code_verifier, "nonce": nonce}
        return self.claims


@pytest_asyncio.fixture
async def api(conn):
    await OrganizationRepo(conn).create("Acme")

    async def _conn_override():
        yield conn

    app.dependency_overrides[get_conn] = _conn_override
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, conn
    app.dependency_overrides.clear()


def _use(fake: FakeOIDC) -> FakeOIDC:
    app.dependency_overrides[get_oidc] = lambda: fake
    return fake


async def _start(client) -> dict[str, str]:
    r = await client.get("/api/v1/auth/sso/login")
    assert r.status_code == 302
    q = parse_qs(urlsplit(r.headers["location"]).query)
    return {k: v[0] for k, v in q.items()}


# ── SSO ──────────────────────────────────────────────────────────────────────
async def test_sso_login_redirects_with_pkce_nonce_and_bound_state(api) -> None:
    client, _conn = api
    _use(FakeOIDC())
    r = await client.get("/api/v1/auth/sso/login")
    assert r.status_code == 302
    assert "idp.example/authorize" in r.headers["location"]
    set_cookie = r.headers["set-cookie"].lower()
    assert "httponly" in set_cookie and "samesite=lax" in set_cookie
    q = parse_qs(urlsplit(r.headers["location"]).query)
    assert q["code_challenge_method"] == ["S256"]
    assert q["state"][0] and q["nonce"][0] and q["code_challenge"][0]


async def test_sso_callback_provisions_and_issues_tokens(api) -> None:
    client, conn = api
    fake = _use(FakeOIDC())
    params = await _start(client)
    r = await client.get(f"/api/v1/auth/sso/callback?code=abc&state={params['state']}")
    assert r.status_code == 200
    assert "access_token" in r.json()

    # PKCE verifier and nonce from the browser-bound flow reach the token exchange.
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(fake.exchanged["code_verifier"].encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    assert challenge == params["code_challenge"]
    assert fake.exchanged["nonce"] == params["nonce"]

    user = await UserRepo(conn).get_by_email("alice@corp.example")
    assert user is not None
    assert user.auth_provider == "oidc"
    assert user.external_id == "idp-sub-123"
    linked = await conn.fetchval(
        "SELECT user_id FROM user_identities WHERE issuer = $1 AND subject = $2",
        ISSUER,
        "idp-sub-123",
    )
    assert linked == user.id

    # The one-time flow cookie is consumed: replaying the callback fails.
    r = await client.get(f"/api/v1/auth/sso/callback?code=abc&state={params['state']}")
    assert r.status_code == 400


async def test_sso_callback_rejects_bad_state(api) -> None:
    client, _conn = api
    _use(FakeOIDC())
    await _start(client)
    r = await client.get("/api/v1/auth/sso/callback?code=abc&state=forged")
    assert r.status_code == 400


async def test_sso_callback_rejects_state_not_bound_to_browser(api) -> None:
    client, _conn = api
    _use(FakeOIDC())
    params = await _start(client)
    client.cookies.clear()  # e.g. a victim's browser that never started the flow
    r = await client.get(f"/api/v1/auth/sso/callback?code=abc&state={params['state']}")
    assert r.status_code == 400


async def _callback(client) -> httpx.Response:
    params = await _start(client)
    return await client.get(f"/api/v1/auth/sso/callback?code=abc&state={params['state']}")


async def test_sso_requires_verified_email_for_first_link(api) -> None:
    client, conn = api
    _use(FakeOIDC(OIDCClaims("sub-x", "eve@corp.example", email_verified=False, issuer=ISSUER)))
    assert (await _callback(client)).status_code == 403
    assert await UserRepo(conn).get_by_email("eve@corp.example") is None


async def test_sso_never_links_to_local_password_account(api) -> None:
    client, conn = api
    victim = await UserRepo(conn).create("ceo@corp.example", "argon-hash", "STAFF")
    _use(FakeOIDC(OIDCClaims("attacker", "ceo@corp.example", email_verified=True, issuer=ISSUER)))
    assert (await _callback(client)).status_code == 403
    assert (
        await conn.fetchval("SELECT count(*) FROM user_identities WHERE user_id = $1", victim.id)
        == 0
    )
    assert (await UserRepo(conn).get(victim.id)).auth_provider == "local"


async def test_sso_never_links_to_super_admin(api) -> None:
    client, conn = api
    await conn.execute(
        "INSERT INTO users (email, password_hash, role, auth_provider)"
        " VALUES ('root@corp.example', '!', 'SUPER_ADMIN', 'scim')"
    )
    _use(FakeOIDC(OIDCClaims("sub-r", "root@corp.example", email_verified=True, issuer=ISSUER)))
    assert (await _callback(client)).status_code == 403


async def test_sso_links_existing_idp_user_by_verified_email(api) -> None:
    client, conn = api
    scim_user = await UserRepo(conn).provision_external(
        "bob@corp.example", "STAFF", org_id=None, auth_provider="scim", external_id="ext-1"
    )
    _use(FakeOIDC(OIDCClaims("sub-bob", "bob@corp.example", email_verified=True, issuer=ISSUER)))
    assert (await _callback(client)).status_code == 200
    assert (
        await conn.fetchval("SELECT user_id FROM user_identities WHERE subject = 'sub-bob'")
        == scim_user.id
    )


async def test_sso_matches_on_issuer_subject_not_email(api) -> None:
    client, conn = api
    _use(FakeOIDC())
    assert (await _callback(client)).status_code == 200
    first = await UserRepo(conn).get_by_email("alice@corp.example")
    # Email changed (and unverified) at the IdP: still the same linked account.
    _use(FakeOIDC(OIDCClaims("idp-sub-123", "renamed@corp.example", False, ISSUER)))
    r = await _callback(client)
    assert r.status_code == 200
    assert await UserRepo(conn).get_by_email("renamed@corp.example") is None
    assert jwt.decode(r.json()["access_token"], options={"verify_signature": False})["sub"] == str(
        first.id
    )


async def test_sso_never_reactivates_deactivated_user(api) -> None:
    client, conn = api
    _use(FakeOIDC())
    assert (await _callback(client)).status_code == 200
    user = await UserRepo(conn).get_by_email("alice@corp.example")
    await UserRepo(conn).set_active(user.id, False)
    assert (await _callback(client)).status_code == 403
    assert (await UserRepo(conn).get(user.id)).is_active is False


@pytest.mark.parametrize(
    ("configured", "provisioned"),
    [("SUPER_ADMIN", "STAFF"), ("WORKSPACE_ADMIN", "WORKSPACE_ADMIN")],
)
async def test_sso_default_role_is_capped_below_super_admin(
    api, monkeypatch, configured, provisioned
) -> None:
    client, conn = api
    monkeypatch.setattr(settings, "oidc_default_role", configured)
    _use(FakeOIDC())
    assert (await _callback(client)).status_code == 200
    user = await UserRepo(conn).get_by_email("alice@corp.example")
    assert user.role == provisioned and user.is_platform_admin is False


# ── OIDC client against a mocked IdP (PKCE, nonce, ID-token checks) ─────────
_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwks() -> dict:
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(_KEY.public_key()))
    jwk.update({"kid": "k1", "alg": "RS256", "use": "sig"})
    return {"keys": [jwk]}


def _id_token(key=_KEY, **overrides) -> str:
    now = datetime.now(UTC)
    claims = {
        "iss": ISSUER,
        "aud": "raggie-client",
        "sub": "sub-42",
        "email": "kim@corp.example",
        "email_verified": True,
        "nonce": "the-nonce",
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    claims.update(overrides)
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "k1"})


@pytest.fixture
def idp(monkeypatch):
    monkeypatch.setattr(settings, "oidc_enabled", True)
    monkeypatch.setattr(settings, "oidc_client_id", "raggie-client")
    monkeypatch.setattr(settings, "oidc_client_secret", "s")
    monkeypatch.setattr(settings, "oidc_authorize_url", f"{ISSUER}/authorize")
    monkeypatch.setattr(settings, "oidc_token_url", f"{ISSUER}/token")
    monkeypatch.setattr(settings, "oidc_userinfo_url", f"{ISSUER}/userinfo")
    monkeypatch.setattr(settings, "oidc_issuer", ISSUER)
    monkeypatch.setattr(settings, "oidc_jwks_url", f"{ISSUER}/jwks")
    state: dict = {"id_token": _id_token(), "token_form": None}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            state["token_form"] = parse_qs(request.content.decode())
            return httpx.Response(200, json={"access_token": "at", "id_token": state["id_token"]})
        if request.url.path == "/jwks":
            return httpx.Response(200, json=_jwks())
        if request.url.path == "/userinfo" and state.get("userinfo") is not None:
            return httpx.Response(200, json=state["userinfo"])
        return httpx.Response(404)

    return OIDCClient(transport=httpx.MockTransport(handler)), state


def test_authorize_url_carries_pkce_and_nonce(idp) -> None:
    client, _state = idp
    q = parse_qs(urlsplit(client.authorize_url(state="s", nonce="n", code_challenge="c")).query)
    assert q["code_challenge"] == ["c"] and q["code_challenge_method"] == ["S256"]
    assert q["nonce"] == ["n"] and q["state"] == ["s"]


async def test_exchange_verifies_id_token_and_sends_verifier(idp) -> None:
    client, state = idp
    claims = await client.exchange_code("code", code_verifier="v" * 50, nonce="the-nonce")
    assert claims == OIDCClaims("sub-42", "kim@corp.example", True, ISSUER)
    assert state["token_form"]["code_verifier"] == ["v" * 50]


@pytest.mark.parametrize(
    "token",
    [
        _id_token(nonce="replayed-nonce"),
        _id_token(aud="someone-else"),
        _id_token(iss="https://evil.example"),
        _id_token(key=_OTHER_KEY),
        _id_token(exp=datetime.now(UTC) - timedelta(minutes=1)),
    ],
    ids=["nonce", "audience", "issuer", "signature", "expired"],
)
async def test_exchange_rejects_bad_id_token(idp, token) -> None:
    client, state = idp
    state["id_token"] = token
    with pytest.raises(OIDCError):
        await client.exchange_code("code", code_verifier="v" * 50, nonce="the-nonce")


async def test_exchange_takes_email_from_userinfo_of_the_same_subject(idp) -> None:
    client, state = idp
    state["id_token"] = _id_token(email=None, email_verified=None)
    state["userinfo"] = {"sub": "sub-42", "email": "kim@corp.example", "email_verified": True}
    claims = await client.exchange_code("code", code_verifier="v" * 50, nonce="the-nonce")
    assert claims == OIDCClaims("sub-42", "kim@corp.example", True, ISSUER)


async def test_exchange_rejects_userinfo_of_another_subject(idp) -> None:
    # A userinfo answer for a different principal must not lend its email
    # to the ID token's subject.
    client, state = idp
    state["id_token"] = _id_token(email=None, email_verified=None)
    state["userinfo"] = {"sub": "victim", "email": "ceo@corp.example", "email_verified": True}
    with pytest.raises(OIDCError, match="userinfo subject"):
        await client.exchange_code("code", code_verifier="v" * 50, nonce="the-nonce")


# ── SCIM ─────────────────────────────────────────────────────────────────────
async def test_scim_requires_token(api, monkeypatch) -> None:
    client, _conn = api
    monkeypatch.setattr(settings, "scim_enabled", True)
    monkeypatch.setattr(settings, "scim_bearer_token", "scim-secret")
    monkeypatch.setattr(settings, "scim_org_id", "00000000-0000-0000-0000-000000000001")
    r = await client.get("/scim/v2/Users")  # no Authorization
    assert r.status_code == 401


async def test_scim_token_compared_in_constant_time(api, monkeypatch) -> None:
    client, _conn = api
    monkeypatch.setattr(settings, "scim_enabled", True)
    monkeypatch.setattr(settings, "scim_bearer_token", "scim-secret")
    monkeypatch.setattr(settings, "scim_org_id", "00000000-0000-0000-0000-000000000001")
    calls: list[tuple] = []
    real = scim_api.hmac.compare_digest

    def spy(a, b):
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(scim_api.hmac, "compare_digest", spy)
    r = await client.get("/scim/v2/Users", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401 and calls
    # Non-ASCII input must be a clean 401, not a TypeError from compare_digest.
    r = await client.get("/scim/v2/Users", headers={"Authorization": "Bearer şifre".encode()})
    assert r.status_code == 401


async def test_scim_disabled_is_404(api, monkeypatch) -> None:
    client, _conn = api
    monkeypatch.setattr(settings, "scim_enabled", False)
    r = await client.get("/scim/v2/Users", headers={"Authorization": "Bearer x"})
    assert r.status_code == 404


@pytest_asyncio.fixture
async def scim(api, monkeypatch):
    """SCIM enabled and bound to one tenant (SCIM_ORG_ID); a second org exists."""
    client, conn = api
    org = await OrganizationRepo(conn).create("SCIM Tenant")
    other = await OrganizationRepo(conn).create("Other Tenant")
    monkeypatch.setattr(settings, "scim_enabled", True)
    monkeypatch.setattr(settings, "scim_bearer_token", "scim-secret")
    monkeypatch.setattr(settings, "scim_org_id", str(org.id))
    client.headers["Authorization"] = "Bearer scim-secret"
    yield client, conn, org, other
    client.headers.pop("Authorization", None)


async def test_scim_requires_tenant_binding(api, monkeypatch) -> None:
    client, _conn = api
    monkeypatch.setattr(settings, "scim_enabled", True)
    monkeypatch.setattr(settings, "scim_bearer_token", "scim-secret")
    monkeypatch.setattr(settings, "scim_org_id", "")
    r = await client.get("/scim/v2/Users", headers={"Authorization": "Bearer scim-secret"})
    assert r.status_code == 404  # fail closed: SCIM without a tenant is not enabled


async def test_scim_reads_are_scoped_to_its_org(scim) -> None:
    client, conn, org, other = scim
    mine = await UserRepo(conn).create("mine@scim.test", "h", "STAFF", org_id=org.id)
    theirs = await UserRepo(conn).create("theirs@other.test", "h", "STAFF", org_id=other.id)
    names = {u["userName"] for u in (await client.get("/scim/v2/Users")).json()["Resources"]}
    assert "mine@scim.test" in names and "theirs@other.test" not in names
    assert (await client.get(f"/scim/v2/Users/{mine.id}")).status_code == 200
    assert (await client.get(f"/scim/v2/Users/{theirs.id}")).status_code == 404
    r = await client.patch(
        f"/scim/v2/Users/{theirs.id}",
        json={"Operations": [{"op": "replace", "value": {"active": False}}]},
    )
    assert r.status_code == 404
    assert (await client.delete(f"/scim/v2/Users/{theirs.id}")).status_code == 404
    assert (await UserRepo(conn).get(theirs.id)).is_active is True


async def test_scim_post_never_takes_over_existing_accounts(scim) -> None:
    client, conn, org, other = scim
    local = await UserRepo(conn).create("ceo@scim.test", "argon", "SUPER_ADMIN", org_id=org.id)
    await UserRepo(conn).set_active(local.id, False)  # deactivated by an admin
    foreign = await UserRepo(conn).create("x@other.test", "argon", "STAFF", org_id=other.id)
    for email in ("ceo@scim.test", "x@other.test"):
        r = await client.post("/scim/v2/Users", json={"userName": email, "externalId": "e"})
        assert r.status_code == 409 and r.json()["scimType"] == "uniqueness"
    after = await UserRepo(conn).get(local.id)
    assert after.auth_provider == "local" and after.is_active is False
    assert (await UserRepo(conn).get(foreign.id)).auth_provider == "local"


async def test_scim_post_never_touches_another_orgs_scim_user(scim) -> None:
    client, conn, _org, other = scim
    foreign = await UserRepo(conn).create_external(
        "sync@other.test", "STAFF", org_id=other.id, auth_provider="scim", external_id="ext-o"
    )
    r = await client.post(
        "/scim/v2/Users",
        json={"userName": "sync@other.test", "externalId": "ext-o", "active": False},
    )
    assert r.status_code == 409 and r.json()["scimType"] == "uniqueness"
    after = await UserRepo(conn).get(foreign.id)
    assert after.is_active is True and after.org_id == other.id


async def test_scim_cannot_reactivate_admin_deactivated_non_scim_user(scim) -> None:
    client, conn, org, _other = scim
    local = await UserRepo(conn).create("l@scim.test", "argon", "STAFF", org_id=org.id)
    await UserRepo(conn).set_active(local.id, False)
    r = await client.patch(
        f"/scim/v2/Users/{local.id}",
        json={"Operations": [{"op": "replace", "value": {"active": True}}]},
    )
    assert r.status_code == 409
    assert (await UserRepo(conn).get(local.id)).is_active is False
    assert (await client.delete(f"/scim/v2/Users/{local.id}")).status_code == 409


async def test_scim_post_is_idempotent_for_scim_managed_user(scim) -> None:
    client, conn, org, _other = scim
    body = {"userName": "sync@scim.test", "externalId": "ext-sync"}
    first = await client.post("/scim/v2/Users", json=body)
    assert first.status_code == 201
    again = await client.post("/scim/v2/Users", json=body)
    assert again.status_code == 201 and again.json()["id"] == first.json()["id"]
    user = await UserRepo(conn).get_by_email("sync@scim.test")
    assert user.org_id == org.id and user.auth_provider == "scim"


async def test_scim_groups_are_scoped_to_its_org(scim) -> None:
    client, conn, org, other = scim
    from raggie_control_plane.db.repositories import TeamRepo

    await TeamRepo(conn).create(other.id, "Foreign Team")
    r = await client.post("/scim/v2/Groups", json={"displayName": "Synced"})
    assert r.status_code == 201
    team = await TeamRepo(conn).get(__import__("uuid").UUID(r.json()["id"]))
    assert team.org_id == org.id
    names = {g["displayName"] for g in (await client.get("/scim/v2/Groups")).json()["Resources"]}
    assert "Synced" in names and "Foreign Team" not in names


async def test_scim_user_lifecycle(api, monkeypatch) -> None:
    client, conn = api
    monkeypatch.setattr(settings, "scim_enabled", True)
    monkeypatch.setattr(settings, "scim_bearer_token", "scim-secret")
    tenant = await OrganizationRepo(conn).create("Lifecycle Tenant")
    monkeypatch.setattr(settings, "scim_org_id", str(tenant.id))
    h = {"Authorization": "Bearer scim-secret"}

    # provision
    r = await client.post(
        "/scim/v2/Users",
        headers=h,
        json={"userName": "bob@corp.example", "externalId": "ext-9"},
    )
    assert r.status_code == 201
    uid = r.json()["id"]
    assert r.json()["active"] is True

    # appears in the list
    lst = await client.get("/scim/v2/Users", headers=h)
    assert any(u["userName"] == "bob@corp.example" for u in lst.json()["Resources"])

    # deactivate via PATCH replace active:false
    r = await client.patch(
        f"/scim/v2/Users/{uid}",
        headers=h,
        json={"Operations": [{"op": "replace", "value": {"active": False}}]},
    )
    assert r.status_code == 200 and r.json()["active"] is False
    user = await UserRepo(conn).get_by_email("bob@corp.example")
    assert user is not None and user.is_active is False

    # delete
    r = await client.delete(f"/scim/v2/Users/{uid}", headers=h)
    assert r.status_code == 204
    assert await UserRepo(conn).get_by_email("bob@corp.example") is None
