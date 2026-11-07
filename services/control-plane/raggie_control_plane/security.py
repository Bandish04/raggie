# SPDX-License-Identifier: Apache-2.0

"""Password hashing, JWT issuance/verification, and invite-token helpers."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from pydantic import AfterValidator

from raggie_control_plane.config import settings

_ph = PasswordHasher()  # argon2id with sensible defaults
_ALG = "HS256"


# ── passwords ────────────────────────────────────────────────
def hash_password(password: str) -> str:
    return _ph.hash(password)


# One policy for every path that sets a password (bootstrap, invite accept,
# change-password, admin create). Length is what matters; the upper bound keeps
# argon2 hashing of absurd inputs from becoming a CPU sink.
MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 1024


def check_password_policy(password: str) -> str:
    if not password.strip():
        raise ValueError("password must not be blank")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise ValueError(f"password must be at most {MAX_PASSWORD_LENGTH} characters")
    return password


# Use as a pydantic field type: violations surface as a 422 with the reason.
NewPassword = Annotated[str, AfterValidator(check_password_policy)]


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        # Wrong password, or a sentinel/non-argon2 hash (SSO/SCIM users) — never
        # a successful login.
        return False


# ── JWT ──────────────────────────────────────────────────────
def create_access_token(user_id: UUID, role: str, org_id: UUID | None, session_id: UUID) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": str(role),
        "org_id": str(org_id) if org_id else None,
        "sid": str(session_id),
        "type": "access",
        "aud": "admin",  # admin surface; widget tokens (aud=widget) are never valid here
        "iat": now,
        "exp": now + timedelta(seconds=settings.jwt_access_ttl_seconds),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_ALG)


def create_refresh_token(user_id: UUID, session_id: UUID) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "sid": str(session_id),
        "jti": secrets.token_urlsafe(16),
        "type": "refresh",
        "aud": "admin",
        "iat": now,
        "exp": now + timedelta(seconds=settings.jwt_refresh_ttl_seconds),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_ALG)


def decode_token(token: str, *, audience: str = "admin") -> dict[str, Any]:
    """Decode and verify a token. Raises jwt.PyJWTError on failure."""
    return jwt.decode(token, settings.jwt_secret, algorithms=[_ALG], audience=audience)


def hash_token(token: str) -> str:
    """One-way representation used for refresh-token rotation checks."""
    return hashlib.sha256(token.encode()).hexdigest()


# ── invite tokens ────────────────────────────────────────────
def generate_invite_token() -> tuple[str, str]:
    """Return (raw_token, token_hash). Only the hash is stored; the raw token is
    shown once, for the invite copy-link."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_invite_token(raw)


def hash_invite_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()
