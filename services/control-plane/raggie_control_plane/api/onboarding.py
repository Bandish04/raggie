# SPDX-License-Identifier: Apache-2.0

"""Interactive first-run onboarding.

Setup state -> bootstrap (first super admin + org) -> choose usage type (creates
the default workspace; EXTERNAL yields the embed snippet, INTERNAL an invite
copy-link) -> system marked onboarded.
"""

from __future__ import annotations

from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from raggie_control_plane.api.deps import get_conn, get_current_user
from raggie_control_plane.auth.service import AuthService
from raggie_control_plane.auth.setup_token import (
    BOOTSTRAP_LOCK_KEY,
    setup_token_required,
    verify_setup_token,
)
from raggie_control_plane.authz import is_platform_admin
from raggie_control_plane.config import settings
from raggie_control_plane.db.repositories import (
    OrganizationRepo,
    SettingsRepo,
    UserRepo,
    WorkspaceRepo,
)
from raggie_control_plane.models import User, Workspace, WorkspaceType
from raggie_control_plane.security import NewPassword

router = APIRouter(prefix="/api/v1/onboarding", tags=["onboarding"])


class StateOut(BaseModel):
    onboarded: bool
    has_super_admin: bool
    # True while bootstrap still needs the one-time `setup_token` (the web shows
    # the field). False once a super admin exists or in development.
    setup_token_required: bool


@router.get("/state", response_model=StateOut)
async def state(conn: asyncpg.Connection = Depends(get_conn)) -> StateOut:
    settings_repo = SettingsRepo(conn)
    await settings_repo.ensure_row()
    has_super_admin = await UserRepo(conn).super_admin_exists()
    return StateOut(
        onboarded=await settings_repo.is_onboarded(),
        has_super_admin=has_super_admin,
        setup_token_required=not has_super_admin and setup_token_required(),
    )


class BootstrapIn(BaseModel):
    email: str
    password: NewPassword
    org_name: str
    setup_token: str | None = None


class BootstrapOut(BaseModel):
    user_id: UUID
    org_id: UUID
    access_token: str
    refresh_token: str


@router.post("/bootstrap", response_model=BootstrapOut, status_code=status.HTTP_201_CREATED)
async def bootstrap(
    body: BootstrapIn, conn: asyncpg.Connection = Depends(get_conn)
) -> BootstrapOut:
    async with conn.transaction():
        # Serialize concurrent attempts so the existence check and the insert
        # are atomic: exactly one caller can ever become the first admin.
        await conn.execute("SELECT pg_advisory_xact_lock($1)", BOOTSTRAP_LOCK_KEY)
        if await UserRepo(conn).super_admin_exists():
            raise HTTPException(status.HTTP_409_CONFLICT, "already bootstrapped")
        if not await verify_setup_token(conn, body.setup_token):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "invalid or missing setup token")
        org = await OrganizationRepo(conn).create(body.org_name)
        user = await AuthService(conn).register(
            body.email, body.password, "SUPER_ADMIN", org_id=org.id, is_platform_admin=True
        )
        await SettingsRepo(conn).clear_setup_token_hash()
    tokens = await AuthService(conn).issue_tokens(user)
    return BootstrapOut(
        user_id=user.id,
        org_id=org.id,
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
    )


class WorkspaceSetupIn(BaseModel):
    type: WorkspaceType
    name: str
    invite_email: str | None = None  # INTERNAL: optionally invite a first teammate


class WorkspaceSetupOut(BaseModel):
    workspace: Workspace
    embed_snippet: str | None = None  # EXTERNAL: the widget <script> embed code
    invite_token: str | None = None  # INTERNAL copy-link token (shown once)
    invite_accept_path: str | None = None


@router.post(
    "/workspace",
    response_model=WorkspaceSetupOut,
    status_code=status.HTTP_201_CREATED,
)
async def setup_workspace(
    body: WorkspaceSetupIn,
    user: User = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_conn),
) -> WorkspaceSetupOut:
    # The wizard flips the platform-wide is_onboarded flag, so it belongs to the
    # platform admin (the bootstrap user). Org SUPER_ADMINs create workspaces
    # through the regular admin API instead.
    if not is_platform_admin(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "only the setup admin may onboard")
    if user.org_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "setup admin has no organization")

    embed_snippet: str | None = None
    invite_token: str | None = None
    invite_accept_path: str | None = None

    async with conn.transaction():
        ws = await WorkspaceRepo(conn).create(user.org_id, body.name, str(body.type))
        if body.type == WorkspaceType.EXTERNAL:
            embed_snippet = (
                f'<script src="{settings.widget_embed_base_url}'
                f'/widgets/embed.js?id={ws.id}"></script>'
            )
        elif body.invite_email:
            _invite, raw = await AuthService(conn).create_invite(
                user.org_id,
                body.invite_email,
                "STAFF",
                created_by=user.id,
                workspace_id=ws.id,
            )
            invite_token = raw
            invite_accept_path = f"/onboarding/accept?token={raw}"
        await SettingsRepo(conn).set_onboarded(True)

    return WorkspaceSetupOut(
        workspace=ws,
        embed_snippet=embed_snippet,
        invite_token=invite_token,
        invite_accept_path=invite_accept_path,
    )
