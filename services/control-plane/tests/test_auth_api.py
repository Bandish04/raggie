# SPDX-License-Identifier: Apache-2.0

from uuid import uuid4


def test_login_bad_credentials_returns_401(client) -> None:
    # Unique per run: failed logins feed the (persistent) per-account lockout.
    r = client.post(
        "/api/v1/auth/login", json={"email": f"nobody-{uuid4()}@example.com", "password": "x"}
    )
    assert r.status_code == 401


def test_me_requires_a_token(client) -> None:
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401


def test_accept_invalid_invite_returns_400(client) -> None:
    r = client.post(
        "/api/v1/auth/invites/accept",
        json={"token": "bogus", "password": "valid-password"},
    )
    assert r.status_code == 400
