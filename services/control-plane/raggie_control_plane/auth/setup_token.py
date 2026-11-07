# SPDX-License-Identifier: Apache-2.0

"""One-time setup token guarding POST /onboarding/bootstrap.

Until the first super admin exists, anyone who can reach the API could claim
the platform. Outside development the bootstrap therefore requires a token the
operator proves possession of: SETUP_TOKEN from the environment, or — when that
is unset — a random token generated at first boot whose plaintext is logged
once (only its sha256 is persisted, and it is cleared once used).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets

import asyncpg

from raggie_control_plane.config import settings
from raggie_control_plane.db.repositories import SettingsRepo, UserRepo

log = logging.getLogger("control-plane.setup")

# Key for pg_advisory_xact_lock serializing concurrent bootstrap attempts.
BOOTSTRAP_LOCK_KEY = 0x5241474749450001  # "RAGGIE" + 1


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def setup_token_required() -> bool:
    return bool(settings.setup_token) or not settings.allows_insecure_defaults


async def ensure_setup_token(conn: asyncpg.Connection) -> str | None:
    """On a not-yet-bootstrapped install without SETUP_TOKEN (outside
    development), generate the one-time token and log it. Returns the
    plaintext only when this call generated it (exactly one replica wins)."""
    if settings.setup_token or not setup_token_required():
        return None
    if await UserRepo(conn).super_admin_exists():
        return None
    plaintext = secrets.token_urlsafe(32)
    if not await SettingsRepo(conn).set_setup_token_hash_if_absent(_sha256(plaintext)):
        log.warning(
            "Raggie is not set up yet; a setup token was already generated (see the "
            "first boot log). Lost it? Set SETUP_TOKEN and restart."
        )
        return None
    banner = "=" * 72
    # Deliberate, one-time disclosure: printing the first-run token to the
    # operator's log is how they receive it (only its hash is ever stored).
    log.warning(  # nosemgrep: python-logger-credential-disclosure
        "\n%s\n  RAGGIE FIRST-RUN SETUP TOKEN (shown once):\n\n    %s\n\n"
        "  Enter it on the setup screen to create the first administrator.\n%s",
        banner,
        plaintext,
        banner,
    )
    return plaintext


async def verify_setup_token(conn: asyncpg.Connection, presented: str | None) -> bool:
    if not setup_token_required():
        return True
    if not presented:
        return False
    if settings.setup_token:
        return hmac.compare_digest(presented.encode(), settings.setup_token.encode())
    stored = await SettingsRepo(conn).get_setup_token_hash()
    if not stored:
        return False  # fail closed: nothing was generated / it was already used
    return hmac.compare_digest(_sha256(presented).encode(), stored.encode())
