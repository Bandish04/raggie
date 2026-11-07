# SPDX-License-Identifier: Apache-2.0

"""Shared FastAPI dependencies: per-request DB connection and current user."""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID

import asyncpg
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from raggie_control_plane.authz import Action, Authorizer, is_platform_admin
from raggie_control_plane.db.repositories import AuthSessionRepo, UserRepo
from raggie_control_plane.embeddings_profile import (
    EmbeddingsProfile,
    IngestBlockedError,
    IngestTarget,
)
from raggie_control_plane.infra.objectstore import ObjectStore
from raggie_control_plane.infra.publisher import EventPublisher
from raggie_control_plane.models import User
from raggie_control_plane.security import decode_token

_bearer = HTTPBearer(auto_error=False)


async def get_conn(request: Request) -> AsyncIterator[asyncpg.Connection]:
    pool: asyncpg.Pool = request.app.state.pool
    async with pool.acquire() as conn:
        yield conn


async def get_object_store(request: Request) -> ObjectStore:
    return request.app.state.object_store


async def get_event_publisher(request: Request) -> EventPublisher:
    return request.app.state.event_publisher


async def get_embeddings_profile(request: Request) -> EmbeddingsProfile:
    return request.app.state.embeddings_profile


async def ingest_target(profile: EmbeddingsProfile, conn: asyncpg.Connection) -> IngestTarget:
    """The gateway's collection + fingerprint for new vectors, or the HTTP error
    that explains why ingestion is refused right now (409 mismatch / 503 unknown)."""
    try:
        return await profile.ingest_target(conn)
    except IngestBlockedError as exc:
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
        raise HTTPException(exc.status_code, exc.detail, headers=headers) from exc


async def get_access_claims(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    try:
        payload = decode_token(creds.credentials)
    except jwt.InvalidAudienceError as exc:
        # Widget isolation: a well-formed token minted for a different surface
        # (e.g. aud=widget) is authenticated but never valid on the admin
        # surface — reject as forbidden, not merely unauthenticated.
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "token not valid for the admin surface"
        ) from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token") from exc
    if payload.get("type") != "access":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not an access token")
    if not payload.get("sub") or not payload.get("sid"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token claims")
    return payload


async def get_current_user(
    payload: dict = Depends(get_access_claims),
    conn: asyncpg.Connection = Depends(get_conn),
) -> User:
    try:
        user_id = UUID(str(payload["sub"]))
        session_id = UUID(str(payload["sid"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token claims") from exc
    user = await UserRepo(conn).get(user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unknown user")
    if not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "inactive user")
    if not await AuthSessionRepo(conn).is_active(session_id, user.id):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "session revoked or expired")
    return user


def ensure_platform_admin(user: User) -> None:
    """Platform-wide state (global settings, operator credentials) is reserved
    for the platform admin; an org SUPER_ADMIN is forbidden."""
    if not is_platform_admin(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")


def require_system():
    """Guard: caller must be the platform admin (``users.is_platform_admin``)."""

    async def dep(
        user: User = Depends(get_current_user),
        conn: asyncpg.Connection = Depends(get_conn),
    ) -> User:
        if not await Authorizer(conn).resolve(user, Action.MANAGE_SYSTEM):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")
        return user

    return dep


def require_org(action: Action):
    """Guard for org-scoped actions; reads ``org_id`` from the path."""

    async def dep(
        org_id: UUID,
        user: User = Depends(get_current_user),
        conn: asyncpg.Connection = Depends(get_conn),
    ) -> User:
        if not await Authorizer(conn).resolve(user, action, org_id=org_id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")
        return user

    return dep


def require_workspace(action: Action):
    """Guard for workspace-scoped actions; reads ``workspace_id`` from the path."""

    async def dep(
        workspace_id: UUID,
        user: User = Depends(get_current_user),
        conn: asyncpg.Connection = Depends(get_conn),
    ) -> User:
        if not await Authorizer(conn).resolve(user, action, workspace_id=workspace_id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")
        return user

    return dep
