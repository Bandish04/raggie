# SPDX-License-Identifier: Apache-2.0

"""Auth service: registration, login (JWT), and the invite-token flow."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import asyncpg
import jwt

from raggie_control_plane.auth.identity import LocalIdentityProvider
from raggie_control_plane.auth.oidc import OIDCClaims
from raggie_control_plane.config import settings
from raggie_control_plane.db.repositories import (
    AuthSessionRepo,
    InviteRepo,
    MembershipRepo,
    UserIdentityRepo,
    UserRepo,
)
from raggie_control_plane.models import Invite, Role, User
from raggie_control_plane.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_invite_token,
    hash_invite_token,
    hash_password,
    hash_token,
)

log = logging.getLogger("control-plane.auth")


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str


class SSOLinkError(Exception):
    """An SSO identity may not be signed in / linked (reason is user-safe)."""


# Roles SSO may auto-provision. A (mis)configured OIDC_DEFAULT_ROLE can never
# mint org SUPER_ADMINs for whoever the IdP vouches for.
_SSO_PROVISION_ROLES = {Role.STAFF, Role.WORKSPACE_ADMIN}


class AuthService:
    def __init__(self, conn: asyncpg.Connection) -> None:
        self.conn = conn
        self.users = UserRepo(conn)
        self.sessions = AuthSessionRepo(conn)
        self.invites = InviteRepo(conn)
        self.members = MembershipRepo(conn)

    async def register(
        self,
        email: str,
        password: str,
        role: str,
        *,
        org_id: UUID | None = None,
        is_platform_admin: bool = False,
    ) -> User:
        return await self.users.create(
            email,
            hash_password(password),
            role,
            org_id=org_id,
            is_platform_admin=is_platform_admin,
        )

    async def login(self, email: str, password: str) -> TokenPair | None:
        user = await LocalIdentityProvider(self.conn).authenticate(email, password)
        if user is None:
            return None
        return await self.issue_tokens(user)

    async def issue_tokens(self, user: User) -> TokenPair:
        session_id = uuid4()
        refresh_token = create_refresh_token(user.id, session_id)
        await self.sessions.create(
            session_id,
            user.id,
            hash_token(refresh_token),
            datetime.now(UTC) + timedelta(seconds=settings.jwt_refresh_ttl_seconds),
        )
        return TokenPair(
            access_token=create_access_token(user.id, user.role, user.org_id, session_id),
            refresh_token=refresh_token,
        )

    async def refresh(self, raw_refresh_token: str) -> TokenPair | None:
        try:
            payload = decode_token(raw_refresh_token)
            if payload.get("type") != "refresh":
                return None
            user_id = UUID(str(payload["sub"]))
            session_id = UUID(str(payload["sid"]))
        except (jwt.PyJWTError, KeyError, TypeError, ValueError):
            return None

        user = await self.users.get(user_id)
        if user is None or not user.is_active:
            return None

        new_refresh = create_refresh_token(user.id, session_id)
        expires_at = datetime.now(UTC) + timedelta(seconds=settings.jwt_refresh_ttl_seconds)
        presented_hash = hash_token(raw_refresh_token)
        if not await self.sessions.rotate(
            session_id,
            user.id,
            presented_hash,
            hash_token(new_refresh),
            expires_at,
        ):
            grace = settings.refresh_reuse_grace_seconds
            if grace > 0 and await self.sessions.rotate_from_predecessor(
                session_id, user.id, presented_hash, hash_token(new_refresh), expires_at, grace
            ):
                log.info("benign concurrent refresh on session %s", session_id)
                return TokenPair(
                    access_token=create_access_token(user.id, user.role, user.org_id, session_id),
                    refresh_token=new_refresh,
                )
            if await self.sessions.revoke_on_reuse(session_id, user.id, presented_hash):
                # Logs ids only (session, user) — never the token or its hash.
                log.warning(  # nosemgrep: python-logger-credential-disclosure
                    "refresh token reuse detected; revoked session %s of user %s",
                    session_id,
                    user.id,
                )
            return None
        return TokenPair(
            access_token=create_access_token(user.id, user.role, user.org_id, session_id),
            refresh_token=new_refresh,
        )

    async def resolve_sso_user(
        self, claims: OIDCClaims, *, org_id: UUID | None, default_role: str
    ) -> User:
        """Map a verified OIDC identity to a Raggie user.

        Identities are matched on (issuer, subject) only. A first-time link by
        email requires email_verified and is refused for local-password
        accounts and SUPER_ADMIN / platform admins (that would let whoever
        controls the IdP email take them over). Deactivated users are never
        reactivated here. Raises SSOLinkError when sign-in must be refused."""
        identities = UserIdentityRepo(self.conn)
        async with self.conn.transaction():
            linked = await identities.get_user(claims.issuer, claims.subject)
            if linked is not None:
                if not linked.is_active:
                    raise SSOLinkError("account is deactivated")
                await identities.touch(claims.issuer, claims.subject, claims.email)
                return linked

            if not claims.email or not claims.email_verified:
                raise SSOLinkError("identity provider did not assert a verified email")
            existing = await self.users.get_by_email(claims.email)
            if existing is not None:
                if not existing.is_active:
                    raise SSOLinkError("account is deactivated")
                if (
                    existing.auth_provider == "local"
                    or existing.role == Role.SUPER_ADMIN
                    or existing.is_platform_admin
                ):
                    raise SSOLinkError(
                        "an account with this email already exists; sign in with your password"
                    )
                await identities.link(existing.id, claims.issuer, claims.subject, claims.email)
                return existing

            role = Role(default_role) if default_role in _SSO_PROVISION_ROLES else Role.STAFF
            # external_id is globally unique (SCIM); only claim it when free.
            taken = await self.users.get_by_external_id(claims.subject)
            user = await self.users.create_external(
                claims.email,
                str(role),
                org_id=org_id,
                auth_provider="oidc",
                external_id=None if taken else claims.subject,
            )
            await identities.link(user.id, claims.issuer, claims.subject, claims.email)
            return user

    async def create_invite(
        self,
        org_id: UUID,
        email: str,
        role: str,
        *,
        created_by: UUID | None = None,
        team_id: UUID | None = None,
        workspace_id: UUID | None = None,
        **profile: object,
    ) -> tuple[Invite, str]:
        """Create an invite; returns (invite, raw_token). The raw token is shown
        ONCE for the copy-link and is never stored (only its hash is). Optional
        profile kwargs are seeded onto the invite and merged onto the user when
        it is accepted."""
        raw, token_hash = generate_invite_token()
        expires_at = datetime.now(UTC) + timedelta(seconds=settings.invite_ttl_seconds)
        invite = await self.invites.create(
            org_id,
            email,
            role,
            token_hash,
            expires_at=expires_at,
            created_by=created_by,
            team_id=team_id,
            workspace_id=workspace_id,
            **profile,
        )
        return invite, raw

    # Profile fields an invitee may fill for blanks the admin left empty.
    _ACCEPT_PROFILE_FIELDS = (
        "full_name",
        "job_title",
        "department",
        "manager_user_id",
        "phone",
        "location",
        "timezone",
        "locale",
    )

    async def accept_invite(
        self, raw_token: str, password: str, profile_overrides: dict | None = None
    ) -> tuple[User, TokenPair] | None:
        """Redeem an invite: create the user (admin-seeded profile + invitee-filled
        blanks), apply team/workspace membership, and return an auto-login token
        pair. Returns None for an invalid/expired/revoked token."""
        token_hash = hash_invite_token(raw_token)
        overrides = profile_overrides or {}
        async with self.conn.transaction():
            invite = await self.invites.get_valid_by_hash(token_hash)
            if invite is None:
                return None
            # The invite's seeded value wins; the invitee only fills blanks.
            merged: dict[str, object] = {}
            for field in self._ACCEPT_PROFILE_FIELDS:
                seeded = getattr(invite, field, None)
                value = seeded if seeded is not None else overrides.get(field)
                if value is not None:
                    merged[field] = value
            # Invites created before the manager check may name a user of
            # another org (or one since deleted): admit the invitee without it.
            manager_id = merged.get("manager_user_id")
            if manager_id is not None:
                manager = await self.users.get(manager_id)
                if manager is None or manager.org_id != invite.org_id:
                    log.warning(
                        "invite %s: manager %s is not in the organization; "
                        "accepting without a manager",
                        invite.id,
                        manager_id,
                    )
                    del merged["manager_user_id"]
            user = await self.users.create(
                invite.email,
                hash_password(password),
                invite.role,
                org_id=invite.org_id,
                **merged,
            )
            if invite.team_id is not None:
                await self.members.add_team_member(invite.team_id, user.id, invite.role)
            if invite.workspace_id is not None:
                await self.members.add_workspace_member(invite.workspace_id, user.id, invite.role)
            await self.invites.mark_accepted(invite.id)
        tokens = await self.issue_tokens(user)
        return user, tokens
