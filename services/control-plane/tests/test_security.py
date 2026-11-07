# SPDX-License-Identifier: Apache-2.0

from uuid import uuid4

from raggie_control_plane.security import (
    create_access_token,
    decode_token,
    generate_invite_token,
    hash_invite_token,
    hash_password,
    verify_password,
)


def test_password_hash_roundtrip() -> None:
    h = hash_password("s3cret-pw")
    assert h != "s3cret-pw"
    assert verify_password(h, "s3cret-pw")
    assert not verify_password(h, "wrong")


def test_access_token_roundtrip() -> None:
    uid = uuid4()
    sid = uuid4()
    token = create_access_token(uid, "WORKSPACE_ADMIN", None, sid)
    payload = decode_token(token)
    assert payload["sub"] == str(uid)
    assert payload["role"] == "WORKSPACE_ADMIN"
    assert payload["type"] == "access"
    assert payload["aud"] == "admin"
    assert payload["sid"] == str(sid)


def test_invite_token_hash_is_deterministic() -> None:
    raw, token_hash = generate_invite_token()
    assert hash_invite_token(raw) == token_hash
    assert len(token_hash) == 64  # sha256 hex digest
