# SPDX-License-Identifier: Apache-2.0

import logging
from uuid import UUID

from raggie_control_plane.auth.service import AuthService
from raggie_control_plane.config import settings
from raggie_control_plane.db.repositories import (
    AuthSessionRepo,
    OrganizationRepo,
    TeamRepo,
    UserRepo,
)
from raggie_control_plane.security import decode_token


async def test_register_and_login(conn, monkeypatch) -> None:
    monkeypatch.setattr(settings, "refresh_reuse_grace_seconds", 0)
    org = await OrganizationRepo(conn).create("Acme")
    svc = AuthService(conn)
    user = await svc.register("admin@acme.example", "pw-123456", "WORKSPACE_ADMIN", org_id=org.id)
    assert user.email == "admin@acme.example"

    tokens = await svc.login("admin@acme.example", "pw-123456")
    assert tokens is not None and tokens.access_token and tokens.refresh_token
    claims = decode_token(tokens.access_token)
    assert await AuthSessionRepo(conn).is_active(UUID(claims["sid"]), UUID(claims["sub"]))

    refreshed = await svc.refresh(tokens.refresh_token)
    assert refreshed is not None
    assert refreshed.refresh_token != tokens.refresh_token
    assert await svc.refresh(tokens.refresh_token) is None
    assert decode_token(refreshed.access_token)["sid"] == claims["sid"]
    refreshed_claims = decode_token(refreshed.access_token)
    await svc.users.update_profile(user.id, role="STAFF")
    assert not await AuthSessionRepo(conn).is_active(UUID(refreshed_claims["sid"]), user.id)
    assert await svc.login("admin@acme.example", "wrong-pw") is None
    assert await svc.login("ghost@acme.example", "whatever") is None


async def test_invite_create_and_accept(conn) -> None:
    org = await OrganizationRepo(conn).create("Acme")
    team = await TeamRepo(conn).create(org.id, "Sales")
    svc = AuthService(conn)

    invite, raw = await svc.create_invite(org.id, "new@acme.example", "STAFF", team_id=team.id)
    assert invite.email == "new@acme.example"
    assert raw  # raw token returned once for the copy-link

    result = await svc.accept_invite(raw, "new-pw-123")
    assert result is not None
    user, _tokens = result
    assert user.email == "new@acme.example"
    # the new user can now log in, proving the password was set
    assert await svc.login("new@acme.example", "new-pw-123") is not None
    # the invite is single-use
    assert await svc.accept_invite(raw, "anything") is None


async def test_accept_drops_a_manager_outside_the_org(conn, caplog) -> None:
    # Invites created before the manager check may carry another org's user:
    # the invitee still gets in, just without that manager.
    org, other = (
        await OrganizationRepo(conn).create("Acme"),
        await OrganizationRepo(conn).create("B"),
    )
    users = UserRepo(conn)
    foreign = await users.create("boss@b.test", "h", "STAFF", org_id=other.id)
    own = await users.create("lead@acme.example", "h", "STAFF", org_id=org.id)
    svc = AuthService(conn)
    _bad, bad_raw = await svc.create_invite(
        org.id, "x@acme.example", "STAFF", manager_user_id=foreign.id
    )
    _ok, ok_raw = await svc.create_invite(org.id, "y@acme.example", "STAFF", manager_user_id=own.id)

    with caplog.at_level(logging.WARNING, logger="control-plane.auth"):
        dropped, _tokens = await svc.accept_invite(bad_raw, "new-pw-123")
    kept, _tokens = await svc.accept_invite(ok_raw, "new-pw-123")
    assert dropped.manager_user_id is None and dropped.org_id == org.id
    assert kept.manager_user_id == own.id
    assert any("manager" in r.getMessage() for r in caplog.records)
    assert not any("boss@b.test" in r.getMessage() for r in caplog.records)


async def test_refresh_token_reuse_revokes_whole_session(conn) -> None:
    svc = AuthService(conn)
    user = await svc.register("reuse@acme.example", "pw-123456", "STAFF")
    first = await svc.login("reuse@acme.example", "pw-123456")
    other = await svc.login("reuse@acme.example", "pw-123456")  # a second device
    assert first is not None and other is not None
    sid = UUID(decode_token(first.access_token)["sid"])

    second = await svc.refresh(first.refresh_token)
    assert second is not None
    await _age_rotation(conn, sid, seconds=3600)  # well past the grace window
    # The rotated-out token shows up again (stolen copy): kill the session family.
    assert await svc.refresh(first.refresh_token) is None
    assert not await AuthSessionRepo(conn).is_active(sid, user.id)
    # ...so the legitimate holder's newest token is dead as well.
    assert await svc.refresh(second.refresh_token) is None
    # Other sessions of the same user are untouched.
    other_sid = UUID(decode_token(other.access_token)["sid"])
    assert await AuthSessionRepo(conn).is_active(other_sid, user.id)


async def _age_rotation(conn, sid: UUID, *, seconds: int) -> None:
    await conn.execute(
        "UPDATE auth_sessions SET rotated_at = rotated_at - make_interval(secs => $2)"
        " WHERE id = $1",
        sid,
        seconds,
    )


async def _session(conn, email: str):
    svc = AuthService(conn)
    user = await svc.register(email, "pw-1234567890", "STAFF")
    pair = await svc.login(email, "pw-1234567890")
    return svc, user, pair, UUID(decode_token(pair.access_token)["sid"])


async def test_refresh_reuse_within_grace_window_is_a_benign_race(conn, monkeypatch) -> None:
    monkeypatch.setattr(settings, "refresh_reuse_grace_seconds", 30)
    svc, user, first, sid = await _session(conn, "race@acme.example")
    replica_a = await svc.refresh(first.refresh_token)  # web replica A rotates
    assert replica_a is not None
    # Web replica B presents the same, just-rotated token a moment later.
    replica_b = await svc.refresh(first.refresh_token)
    assert replica_b is not None
    assert decode_token(replica_b.access_token)["sid"] == str(sid)
    assert await AuthSessionRepo(conn).is_active(sid, user.id)
    # Both replicas keep a working token chain (the family stays alive).
    assert await svc.refresh(replica_b.refresh_token) is not None


async def test_refresh_reuse_after_grace_window_revokes(conn, monkeypatch) -> None:
    monkeypatch.setattr(settings, "refresh_reuse_grace_seconds", 30)
    svc, user, first, sid = await _session(conn, "late@acme.example")
    assert await svc.refresh(first.refresh_token) is not None
    await _age_rotation(conn, sid, seconds=31)
    assert await svc.refresh(first.refresh_token) is None
    assert not await AuthSessionRepo(conn).is_active(sid, user.id)


async def test_refresh_reuse_of_older_ancestor_revokes(conn, monkeypatch) -> None:
    monkeypatch.setattr(settings, "refresh_reuse_grace_seconds", 30)
    svc, user, first, sid = await _session(conn, "old@acme.example")
    second = await svc.refresh(first.refresh_token)
    assert second is not None and await svc.refresh(second.refresh_token) is not None
    # `first` is two generations old: never a benign race, even inside the window.
    assert await svc.refresh(first.refresh_token) is None
    assert not await AuthSessionRepo(conn).is_active(sid, user.id)


async def test_refresh_endpoint_returns_200_within_grace(conn, monkeypatch) -> None:
    import httpx
    from httpx import ASGITransport

    from raggie_control_plane.api import ratelimit
    from raggie_control_plane.api.deps import get_conn
    from raggie_control_plane.main import app

    monkeypatch.setattr(settings, "refresh_reuse_grace_seconds", 30)
    monkeypatch.setattr(ratelimit, "_login_limiter", ratelimit.SlidingWindowLimiter(1000, 60))
    _svc, _user, first, _sid = await _session(conn, "api-race@acme.example")

    async def _conn_override():
        yield conn

    app.dependency_overrides[get_conn] = _conn_override
    try:
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            body = {"refresh_token": first.refresh_token}
            assert (await c.post("/api/v1/auth/refresh", json=body)).status_code == 200
            assert (await c.post("/api/v1/auth/refresh", json=body)).status_code == 200
    finally:
        app.dependency_overrides.clear()
