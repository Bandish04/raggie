# SPDX-License-Identifier: Apache-2.0

"""AI / model configuration (platform-wide, on the system_settings singleton).

SUPER_ADMIN curates which chat model ids are offered (chat_allowed_models) and the
platform default (chat_default_model). Any logged-in user reads the curated list
via GET /api/v1/models to populate the chat model picker.

LLM endpoints and API keys are NEVER stored here — the edge resolves canonical
model ids through its environment-backed provider registry. This is a deliberate
KVKK / on-prem decision.
"""

from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from raggie_control_plane.api.deps import ensure_platform_admin, get_conn, get_current_user
from raggie_control_plane.db.repositories import SettingsRepo
from raggie_control_plane.models import User

router = APIRouter(prefix="/api/v1", tags=["ai-config"])


class ModelsOut(BaseModel):
    default_model: str | None = None
    allowed_models: list[str] = []
    # Display aliases: real model id -> friendly name shown in the picker (0012).
    aliases: dict[str, str] = {}


class AIConfigUpdate(BaseModel):
    chat_default_model: str | None = None
    chat_allowed_models: list[str] | None = None
    chat_model_aliases: dict[str, str] | None = None


@router.get("/models", response_model=ModelsOut)
async def list_models(
    user: User = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_conn),
) -> ModelsOut:
    """Any logged-in user: the curated model picker (default + allowed list +
    display aliases for the offered model ids)."""
    cfg = await SettingsRepo(conn).get_ai_config()
    return ModelsOut(
        default_model=cfg["chat_default_model"],
        allowed_models=cfg["chat_allowed_models"],
        aliases=cfg["chat_model_aliases"],
    )


@router.get("/admin/ai-config", response_model=ModelsOut)
async def get_ai_config(
    user: User = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_conn),
) -> ModelsOut:
    ensure_platform_admin(user)
    cfg = await SettingsRepo(conn).get_ai_config()
    return ModelsOut(
        default_model=cfg["chat_default_model"],
        allowed_models=cfg["chat_allowed_models"],
        aliases=cfg["chat_model_aliases"],
    )


@router.put("/admin/ai-config", response_model=ModelsOut)
async def update_ai_config(
    body: AIConfigUpdate,
    user: User = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_conn),
) -> ModelsOut:
    """Patch the curated AI config. A field present in the body is written
    (chat_default_model may be set to null to clear the default); absent fields
    are left untouched. Allowed-model entries are trimmed and de-duplicated;
    chat_model_aliases keys/values are coerced to strings and empty aliases dropped."""
    ensure_platform_admin(user)
    repo = SettingsRepo(conn)
    current = await repo.get_ai_config()
    sent = body.model_fields_set
    default_model = body.chat_default_model
    if default_model is not None:
        default_model = default_model.strip() or None
    allowed: list[str] | None = None
    if "chat_allowed_models" in sent:
        seen: set[str] = set()
        allowed = []
        for raw in body.chat_allowed_models or []:
            name = raw.strip()
            if name and name not in seen:
                seen.add(name)
                allowed.append(name)
    effective_allowed = allowed if "chat_allowed_models" in sent else current["chat_allowed_models"]
    effective_default = (
        default_model if "chat_default_model" in sent else current["chat_default_model"]
    )
    if effective_default is not None and effective_default not in effective_allowed:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "chat_default_model must be present in chat_allowed_models",
        )
    aliases: dict[str, str] | None = None
    if "chat_model_aliases" in sent:
        # Keys (model ids) and values (labels) are coerced to trimmed strings;
        # entries with an empty key or empty alias are dropped. We intentionally
        # keep aliases whose key is not (yet) in allowed_models — harmless extras
        # the picker simply ignores until that id is offered.
        aliases = {}
        for raw_id, raw_label in (body.chat_model_aliases or {}).items():
            mid = str(raw_id).strip()
            label = str(raw_label).strip()
            if mid and label:
                aliases[mid] = label
    cfg = await repo.update_ai_config(
        chat_default_model=default_model,
        chat_allowed_models=allowed,
        chat_model_aliases=aliases,
        set_default="chat_default_model" in sent,
        set_allowed="chat_allowed_models" in sent,
        set_aliases="chat_model_aliases" in sent,
    )
    return ModelsOut(
        default_model=cfg["chat_default_model"],
        allowed_models=cfg["chat_allowed_models"],
        aliases=cfg["chat_model_aliases"],
    )
