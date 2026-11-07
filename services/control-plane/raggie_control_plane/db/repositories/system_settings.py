# SPDX-License-Identifier: Apache-2.0

"""Platform-wide settings (the single system_settings row)."""

from __future__ import annotations

import json

import asyncpg

from raggie_control_plane.db.repositories._common import compose_sql


class SettingsRepo:
    def __init__(self, conn: asyncpg.Connection) -> None:
        self.conn = conn

    async def ensure_row(self) -> None:
        await self.conn.execute(
            "INSERT INTO system_settings(id) VALUES('current') ON CONFLICT (id) DO NOTHING"
        )

    async def is_onboarded(self) -> bool:
        row = await self.conn.fetchrow(
            "SELECT is_onboarded FROM system_settings WHERE id='current'"
        )
        return bool(row and row["is_onboarded"])

    async def set_onboarded(self, value: bool) -> None:
        await self.conn.execute(
            "INSERT INTO system_settings(id, is_onboarded) VALUES('current', $1) "
            "ON CONFLICT (id) DO UPDATE SET is_onboarded = EXCLUDED.is_onboarded",
            value,
        )

    # ── Bootstrap setup token (0024): sha256 only, never the plaintext ───────
    async def get_setup_token_hash(self) -> str | None:
        return await self.conn.fetchval(
            "SELECT setup_token_hash FROM system_settings WHERE id='current'"
        )

    async def set_setup_token_hash_if_absent(self, token_hash: str) -> bool:
        """Store the hash unless one exists (first replica wins). True if stored."""
        await self.ensure_row()
        row = await self.conn.fetchrow(
            "UPDATE system_settings SET setup_token_hash = $1"
            " WHERE id='current' AND setup_token_hash IS NULL RETURNING id",
            token_hash,
        )
        return row is not None

    async def clear_setup_token_hash(self) -> None:
        await self.conn.execute(
            "UPDATE system_settings SET setup_token_hash = NULL WHERE id='current'"
        )

    # ── Re-embed lease (0030) ─────────────────────────────────────────────────
    # One re-embed at a time across replicas. Each call is a single autocommit
    # statement on the row, so it works behind a transaction pooler; times come
    # from the database clock.
    async def acquire_reembed_lease(self, owner: str, ttl_seconds: float) -> bool:
        """Take the lease if it is free or expired (or already ours)."""
        await self.ensure_row()
        row = await self.conn.fetchrow(
            "UPDATE system_settings SET reembed_lease_owner = $1,"
            " reembed_lease_expires_at = now() + make_interval(secs => $2)"
            " WHERE id = 'current' AND (reembed_lease_owner IS NULL"
            " OR reembed_lease_expires_at < now() OR reembed_lease_owner = $1)"
            " RETURNING id",
            owner,
            float(ttl_seconds),
        )
        return row is not None

    async def refresh_reembed_lease(self, owner: str, ttl_seconds: float) -> bool:
        """Extend our lease; False when it expired and someone else took it."""
        row = await self.conn.fetchrow(
            "UPDATE system_settings"
            " SET reembed_lease_expires_at = now() + make_interval(secs => $2)"
            " WHERE id = 'current' AND reembed_lease_owner = $1 RETURNING id",
            owner,
            float(ttl_seconds),
        )
        return row is not None

    async def release_reembed_lease(self, owner: str) -> None:
        await self.conn.execute(
            "UPDATE system_settings SET reembed_lease_owner = NULL,"
            " reembed_lease_expires_at = NULL WHERE id = 'current' AND reembed_lease_owner = $1",
            owner,
        )

    # ── Accepted embedding profile (0026) ────────────────────────────────────
    async def get_embedding_profile(self) -> tuple[str | None, dict | None]:
        """(fingerprint, profile) the platform's documents are indexed under."""
        row = await self.conn.fetchrow(
            "SELECT embedding_fingerprint, embedding_profile FROM system_settings"
            " WHERE id='current'"
        )
        if row is None:
            return None, None
        return row["embedding_fingerprint"], row["embedding_profile"]

    async def store_embedding_profile(
        self, fingerprint: str, profile: dict, *, expected: str | None
    ) -> bool:
        """Compare-and-set: store the profile only while the stored fingerprint is
        still ``expected`` (another replica may have moved it) and something
        actually changes. True when this call changed the row."""
        await self.ensure_row()
        row = await self.conn.fetchrow(
            "UPDATE system_settings SET embedding_fingerprint = $1, embedding_profile = $2"
            " WHERE id='current' AND embedding_fingerprint IS NOT DISTINCT FROM $3"
            " AND (embedding_fingerprint IS DISTINCT FROM $1"
            "      OR embedding_profile IS DISTINCT FROM $2) RETURNING id",
            fingerprint,
            profile,  # the pool's jsonb codec serializes
            expected,
        )
        return row is not None

    # ── White-label branding (0008) ──────────────────────────────────────────
    _BRANDING_COLS = (
        "brand_name",
        "brand_tagline",
        "brand_color",
        "brand_logo_key",
        "brand_logo_type",
        "brand_icon_key",
        "brand_icon_type",
    )

    async def get_branding(self) -> dict:
        await self.ensure_row()
        row = await self.conn.fetchrow(
            compose_sql(
                "SELECT {cols} FROM system_settings WHERE id='current'",
                cols=self._BRANDING_COLS,
            )
        )
        return dict(row) if row else {}

    async def update_branding(self, **fields: object) -> dict:
        """Patch only the supplied branding columns; returns the new branding."""
        await self.ensure_row()
        sets: list[str] = []
        vals: list[object] = []
        for col in self._BRANDING_COLS:
            if col in fields:
                vals.append(fields[col])
                sets.append(f"{col} = ${len(vals)}")
        if sets:
            await self.conn.execute(
                compose_sql("UPDATE system_settings SET {sets} WHERE id='current'", sets=sets),
                *vals,
            )
        return await self.get_branding()

    # ── AI / model config (0010, 0012) ───────────────────────────────────────
    # chat_default_model (nullable) + chat_allowed_models (JSONB string[]) curate
    # the chat model picker; chat_model_aliases (JSONB id->label map, 0012) gives
    # each model id a friendly display name. Provider endpoints/keys stay in the
    # edge's environment-backed registry, never here.
    async def get_ai_config(self) -> dict:
        await self.ensure_row()
        row = await self.conn.fetchrow(
            "SELECT chat_default_model, chat_allowed_models, chat_model_aliases"
            " FROM system_settings WHERE id='current'"
        )
        if row is None:
            return {
                "chat_default_model": None,
                "chat_allowed_models": [],
                "chat_model_aliases": {},
            }
        raw = row["chat_allowed_models"]
        # asyncpg returns JSONB as text unless a codec is registered; be tolerant.
        models = json.loads(raw) if isinstance(raw, str) else (raw or [])
        raw_aliases = row["chat_model_aliases"]
        aliases = json.loads(raw_aliases) if isinstance(raw_aliases, str) else (raw_aliases or {})
        return {
            "chat_default_model": row["chat_default_model"],
            "chat_allowed_models": list(models),
            "chat_model_aliases": dict(aliases),
        }

    async def update_ai_config(
        self,
        *,
        chat_default_model: str | None = None,
        chat_allowed_models: list[str] | None = None,
        chat_model_aliases: dict[str, str] | None = None,
        set_default: bool = False,
        set_allowed: bool = False,
        set_aliases: bool = False,
    ) -> dict:
        """Patch the AI config. set_default/set_allowed/set_aliases gate whether each
        column is written, so a caller can explicitly clear chat_default_model to NULL
        (set_default=True, chat_default_model=None) without it being mistaken for
        'leave unchanged'."""
        await self.ensure_row()
        sets: list[str] = []
        vals: list[object] = []
        if set_default:
            vals.append(chat_default_model)
            sets.append(f"chat_default_model = ${len(vals)}")
        if set_allowed:
            # The pool's JSONB codec serializes Python objects. Passing an already
            # serialized string would store a JSON string instead of an array.
            vals.append(list(chat_allowed_models or []))
            sets.append(f"chat_allowed_models = ${len(vals)}::jsonb")
        if set_aliases:
            vals.append(dict(chat_model_aliases or {}))
            sets.append(f"chat_model_aliases = ${len(vals)}::jsonb")
        if sets:
            await self.conn.execute(
                compose_sql("UPDATE system_settings SET {sets} WHERE id='current'", sets=sets),
                *vals,
            )
        return await self.get_ai_config()
