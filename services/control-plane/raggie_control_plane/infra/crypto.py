# SPDX-License-Identifier: Apache-2.0

"""Symmetric encryption for integration credentials at rest (Fernet).

The key comes from ``INTEGRATION_ENC_KEY`` (a url-safe base64, 32-byte Fernet
key); prefer a ``_FILE``-mounted secret in prod. Integration credentials (OAuth
tokens, API keys) are NEVER stored in plaintext — only the encrypted blob lands
in ``integrations.credentials_enc``.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from raggie_control_plane.config import settings


class CryptoError(RuntimeError):
    """Raised when encryption/decryption is impossible (missing/invalid key)."""


def is_configured() -> bool:
    return bool(settings.integration_enc_key)


def _fernet() -> Fernet:
    key = settings.integration_enc_key
    if not key:
        raise CryptoError("INTEGRATION_ENC_KEY is not configured")
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception as exc:  # noqa: BLE001 — surface any malformed-key error uniformly
        raise CryptoError("INTEGRATION_ENC_KEY is not a valid Fernet key") from exc


def encrypt(plaintext: str) -> str:
    """Encrypt a credential string; returns the url-safe token to store."""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    """Decrypt a stored credential token back to plaintext."""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise CryptoError("could not decrypt credentials (wrong key?)") from exc
