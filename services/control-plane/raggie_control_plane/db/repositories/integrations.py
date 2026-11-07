# SPDX-License-Identifier: Apache-2.0

"""Data-source integrations."""

from __future__ import annotations

from uuid import UUID

import asyncpg

from raggie_control_plane.models import Integration


class IntegrationRepo:
    """Generic external-integration store (provider-agnostic). Credentials are
    persisted ENCRYPTED (credentials_enc) by the API layer — this repo never sees
    plaintext."""

    def __init__(self, conn: asyncpg.Connection) -> None:
        self.conn = conn

    async def list_by_org(self, org_id: UUID) -> list[Integration]:
        rows = await self.conn.fetch(
            "SELECT * FROM integrations WHERE org_id = $1 ORDER BY created_at DESC", org_id
        )
        return [Integration(**dict(r)) for r in rows]

    async def list_by_scope(self, scope_type: str, scope_id: UUID) -> list[Integration]:
        rows = await self.conn.fetch(
            "SELECT * FROM integrations WHERE scope_type = $1 AND scope_id = $2"
            " ORDER BY created_at DESC",
            scope_type,
            scope_id,
        )
        return [Integration(**dict(r)) for r in rows]

    async def get(self, integration_id: UUID) -> Integration | None:
        row = await self.conn.fetchrow("SELECT * FROM integrations WHERE id = $1", integration_id)
        return Integration(**dict(row)) if row else None

    async def upsert(
        self,
        *,
        org_id: UUID,
        scope_type: str,
        scope_id: UUID,
        provider: str,
        target_workspace_id: UUID | None,
        display_name: str | None,
        credentials_enc: str | None,
        config: dict,
        status: str,
        created_by: UUID | None,
    ) -> Integration:
        """Create or re-connect an integration (unique per scope+provider).
        A NULL credentials_enc keeps the existing one (re-config without re-auth)."""
        row = await self.conn.fetchrow(
            "INSERT INTO integrations"
            " (org_id, scope_type, scope_id, target_workspace_id, provider,"
            "  display_name, credentials_enc, config, status, created_by)"
            " VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9, $10)"
            " ON CONFLICT (scope_type, scope_id, provider) DO UPDATE SET"
            "   target_workspace_id = EXCLUDED.target_workspace_id,"
            "   display_name = EXCLUDED.display_name,"
            "   credentials_enc = COALESCE(EXCLUDED.credentials_enc, integrations.credentials_enc),"
            "   config = EXCLUDED.config, status = EXCLUDED.status,"
            "   last_error = NULL, updated_at = now()"
            " RETURNING *",
            org_id,
            scope_type,
            scope_id,
            target_workspace_id,
            provider,
            display_name,
            credentials_enc,
            config,  # the pool's jsonb codec serializes; json.dumps would double-encode
            status,
            created_by,
        )
        assert row is not None
        return Integration(**dict(row))

    async def delete(self, integration_id: UUID) -> bool:
        result = await self.conn.execute("DELETE FROM integrations WHERE id = $1", integration_id)
        return result.endswith("1")
