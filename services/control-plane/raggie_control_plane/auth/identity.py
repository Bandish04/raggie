# SPDX-License-Identifier: Apache-2.0

"""Identity-provider seam.

Email/password is the default behind this Protocol. SSO (OIDC/SAML) and SCIM
plug into the same seam, so adding a provider needs no change to core auth.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import asyncpg

from raggie_control_plane.db.repositories import UserRepo
from raggie_control_plane.models import User
from raggie_control_plane.security import verify_password


@runtime_checkable
class IdentityProvider(Protocol):
    async def authenticate(self, email: str, password: str) -> User | None: ...


class LocalIdentityProvider:
    """Email + password verification against the users table."""

    def __init__(self, conn: asyncpg.Connection) -> None:
        self.users = UserRepo(conn)

    async def authenticate(self, email: str, password: str) -> User | None:
        password_hash = await self.users.get_password_hash(email)
        if password_hash and verify_password(password_hash, password):
            user = await self.users.get_by_email(email)
            if user is not None and user.is_active:
                return user
        return None
