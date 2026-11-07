# SPDX-License-Identifier: Apache-2.0

"""Workspaces."""

from __future__ import annotations

from uuid import UUID

import asyncpg

from raggie_control_plane.models import Workspace


class WorkspaceRepo:
    def __init__(self, conn: asyncpg.Connection) -> None:
        self.conn = conn

    async def create(
        self,
        org_id: UUID,
        name: str,
        type_: str,
        *,
        team_id: UUID | None = None,
        system_prompt: str = "",
        temperature: float = 0.3,
        widget_primary_color: str = "#3498db",
        web_search_enabled: bool = False,
        personalization_enabled: bool = False,
        memory_enabled: bool = False,
    ) -> Workspace:
        row = await self.conn.fetchrow(
            "INSERT INTO workspaces"
            " (org_id, team_id, name, type, system_prompt, temperature,"
            "  widget_primary_color, web_search_enabled, personalization_enabled,"
            "  memory_enabled)"
            " VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10) RETURNING *",
            org_id,
            team_id,
            name,
            type_,
            system_prompt,
            temperature,
            widget_primary_color,
            web_search_enabled,
            personalization_enabled,
            memory_enabled,
        )
        return Workspace(**dict(row))

    async def update_settings(
        self,
        workspace_id: UUID,
        *,
        web_search_enabled: bool | None = None,
        personalization_enabled: bool | None = None,
        memory_enabled: bool | None = None,
    ) -> Workspace | None:
        """Toggle the per-workspace chat-intelligence flags (NULL leaves a flag
        unchanged)."""
        row = await self.conn.fetchrow(
            "UPDATE workspaces SET"
            "  web_search_enabled = COALESCE($2, web_search_enabled),"
            "  personalization_enabled = COALESCE($3, personalization_enabled),"
            "  memory_enabled = COALESCE($4, memory_enabled),"
            "  updated_at = now()"
            " WHERE id = $1 RETURNING *",
            workspace_id,
            web_search_enabled,
            personalization_enabled,
            memory_enabled,
        )
        return Workspace(**dict(row)) if row else None

    async def get(self, workspace_id: UUID) -> Workspace | None:
        row = await self.conn.fetchrow("SELECT * FROM workspaces WHERE id = $1", workspace_id)
        return Workspace(**dict(row)) if row else None

    async def list_by_org(self, org_id: UUID) -> list[Workspace]:
        rows = await self.conn.fetch(
            "SELECT * FROM workspaces WHERE org_id = $1 ORDER BY created_at", org_id
        )
        return [Workspace(**dict(r)) for r in rows]

    async def list_all(self) -> list[Workspace]:
        rows = await self.conn.fetch("SELECT * FROM workspaces ORDER BY created_at")
        return [Workspace(**dict(r)) for r in rows]

    async def list_by_ids(self, ids: list[UUID]) -> list[Workspace]:
        if not ids:
            return []
        rows = await self.conn.fetch(
            "SELECT * FROM workspaces WHERE id = ANY($1::uuid[]) ORDER BY created_at", ids
        )
        return [Workspace(**dict(r)) for r in rows]

    async def list_by_team_ids(self, team_ids: list[UUID]) -> list[Workspace]:
        """Workspaces directly assigned to any of the given teams (caller passes
        a team's closure descendants for an inherited pool)."""
        if not team_ids:
            return []
        rows = await self.conn.fetch(
            "SELECT * FROM workspaces WHERE team_id = ANY($1::uuid[]) ORDER BY created_at",
            team_ids,
        )
        return [Workspace(**dict(r)) for r in rows]

    async def update_widget_config(
        self,
        workspace_id: UUID,
        *,
        widget_primary_color: str | None = None,
        cors_allowed_origins: list[str] | None = None,
    ) -> Workspace | None:
        """Patch the widget appearance / CORS allow-list. NULL args leave the
        column unchanged (COALESCE). cors_allowed_origins is validated upstream
        (wildcards rejected: a widget must be pinned to explicit origins)."""
        row = await self.conn.fetchrow(
            "UPDATE workspaces SET"
            "  widget_primary_color = COALESCE($2, widget_primary_color),"
            "  cors_allowed_origins = COALESCE($3::jsonb, cors_allowed_origins),"
            "  updated_at = now()"
            " WHERE id = $1 RETURNING *",
            workspace_id,
            widget_primary_color,
            cors_allowed_origins,
        )
        return Workspace(**dict(row)) if row else None
