# SPDX-License-Identifier: Apache-2.0

"""Admin dashboard analytics — real aggregates over the caller's workspaces."""

from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from raggie_control_plane.api.deps import get_conn, get_current_user
from raggie_control_plane.authz import is_platform_admin, visible_workspaces
from raggie_control_plane.db.repositories import AnalyticsRepo, AuditRepo
from raggie_control_plane.models import Role, User

router = APIRouter(prefix="/api/v1/admin", tags=["analytics"])


class DocumentVolume(BaseModel):
    total: int
    pending: int
    processing: int
    success: int
    failed: int


class ActivityPoint(BaseModel):
    date: str
    messages: int


class AnalyticsOut(BaseModel):
    workspaces: int
    documents: DocumentVolume
    conversations: int
    flagged: int
    messages: int
    tokens_used: int
    activity: list[ActivityPoint]


@router.get("/analytics", response_model=AnalyticsOut)
async def analytics(
    user: User = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_conn),
) -> AnalyticsOut:
    ids = [w.id for w in await visible_workspaces(conn, user)]

    data = await AnalyticsRepo(conn).summary(ids)
    return AnalyticsOut(workspaces=len(ids), **data)


class UsageByUser(BaseModel):
    user_id: str | None  # None for the aggregated anonymous-widget row
    email: str
    full_name: str | None
    message_count: int
    total_tokens: int


@router.get("/analytics/usage-by-user", response_model=list[UsageByUser])
async def usage_by_user(
    user: User = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_conn),
) -> list[UsageByUser]:
    """Per-user message volume + token spend, highest first, scoped to the
    caller's accessible workspaces (same scoping as /analytics). Anonymous widget
    traffic is aggregated into one row (user_id=None, email='anonymous')."""
    ids = [w.id for w in await visible_workspaces(conn, user)]

    rows = await AnalyticsRepo(conn).usage_by_user(ids)
    return [UsageByUser(**r) for r in rows]


class FlaggedConversation(BaseModel):
    id: str
    workspace_id: str
    evaluation_score: float
    faithfulness_score: float | None = None
    citation_validity_score: float | None = None
    citation_coverage_score: float | None = None
    preview: str | None
    created_at: str


@router.get("/conversations/flagged", response_model=list[FlaggedConversation])
async def flagged_conversations(
    user: User = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_conn),
) -> list[FlaggedConversation]:
    ids = [w.id for w in await visible_workspaces(conn, user)]

    rows = await AnalyticsRepo(conn).list_flagged(ids)
    return [FlaggedConversation(**r) for r in rows]


@router.get("/audit")
async def audit_log(
    user: User = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_conn),
) -> list[dict]:
    if user.role != Role.SUPER_ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")
    # No org means "no filter" (every org's log): platform admins only.
    if user.org_id is None and not is_platform_admin(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")
    return await AuditRepo(conn).list(org_id=user.org_id)
