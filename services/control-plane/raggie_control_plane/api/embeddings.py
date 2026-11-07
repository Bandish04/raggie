# SPDX-License-Identifier: Apache-2.0

"""Admin view of the embedding profile, and the re-embed switch (platform admin).

GET reports what the embeddings gateway runs (provider, model, collection,
where document text is sent), the profile the indexed documents were accepted
under, the per-fingerprint document counts and the re-embed progress. POST
/reembed accepts the gateway's current profile and re-embeds every live
document still on another one into its collection. The old collection is
never dropped here: that is a separate, manual operation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from raggie_control_plane.api.deps import (
    get_conn,
    get_current_user,
    get_embeddings_profile,
    get_event_publisher,
    require_system,
)
from raggie_control_plane.db.repositories import AuditRepo, DocumentRepo, SettingsRepo
from raggie_control_plane.embeddings_profile import (
    AUDIT_REEMBED_STARTED,
    EmbeddingsInfo,
    EmbeddingsProfile,
    GatewayUnavailableError,
    IngestTarget,
    ReembedBusyError,
    reembed_stale,
)
from raggie_control_plane.infra.publisher import EventPublisher
from raggie_control_plane.models import User

router = APIRouter(prefix="/api/v1/admin/embeddings", tags=["embeddings"])


class FingerprintCount(BaseModel):
    fingerprint: str | None  # None = indexed before fingerprints, profile unknown
    count: int


class ReembedProgress(BaseModel):
    """Live documents targeting ``target_fingerprint``, by ingestion status;
    ``stale`` = live documents still on another (or no) fingerprint."""

    target_fingerprint: str | None
    total: int = 0
    completed: int = 0
    pending: int = 0
    processing: int = 0
    failed: int = 0
    stale: int = 0
    in_progress: bool = False
    last_started_at: datetime | None = None


class EmbeddingsStatus(BaseModel):
    status: Literal["ok", "mismatch", "unknown"]
    policy: str
    ingest_blocked: bool
    detail: str | None  # why ingestion is blocked, admin-facing
    profile: EmbeddingsInfo | None  # the gateway's current profile (GET /v1/info)
    stored_fingerprint: str | None  # the profile the platform accepted
    mismatch: bool
    checked_at: datetime | None
    gateway_error: str | None
    documents: list[FingerprintCount]
    reembed: ReembedProgress


class ReembedIn(BaseModel):
    # The fingerprint the admin saw and confirms; a changed gateway is refused.
    fingerprint: str = Field(pattern=r"^[0-9a-f]{8}$")


class ReembedOut(BaseModel):
    fingerprint: str
    collection: str
    reembedded: int
    skipped: int  # live documents without a retained raw file
    workspaces: int


@router.get("", response_model=EmbeddingsStatus, dependencies=[Depends(require_system())])
async def embeddings_status(
    conn: asyncpg.Connection = Depends(get_conn),
    profile: EmbeddingsProfile = Depends(get_embeddings_profile),
) -> EmbeddingsStatus:
    try:
        # Cached for EMBEDDINGS_INFO_TTL_SECONDS: the card can't hammer the gateway.
        profile.info = await profile.client.get()
        profile.last_error = None
    except GatewayUnavailableError as exc:
        profile.last_error = str(exc)  # keep the last known profile
    await profile.evaluate(conn)
    docs = DocumentRepo(conn)
    target = profile.info.fingerprint if profile.info else profile.stored_fingerprint
    progress = ReembedProgress(target_fingerprint=target)
    if target is not None:
        counts = await docs.reembed_progress(target)
        progress = ReembedProgress(
            target_fingerprint=target,
            **counts,
            in_progress=counts["pending"] + counts["processing"] > 0,
            last_started_at=await AuditRepo(conn).last_recorded_at(AUDIT_REEMBED_STARTED),
        )
    blocked = profile.blocked_reason()
    return EmbeddingsStatus(
        status=profile.status,
        policy=profile.policy,
        ingest_blocked=blocked is not None,
        detail=blocked.detail if blocked else None,
        profile=profile.info,
        stored_fingerprint=profile.stored_fingerprint,
        mismatch=profile.mismatch,
        checked_at=profile.checked_at,
        gateway_error=profile.last_error,
        documents=[
            FingerprintCount(fingerprint=fp, count=n)
            for fp, n in await docs.live_counts_by_fingerprint()
        ],
        reembed=progress,
    )


@router.post("/reembed", response_model=ReembedOut, dependencies=[Depends(require_system())])
async def reembed(
    body: ReembedIn,
    user: User = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_conn),
    publisher: EventPublisher = Depends(get_event_publisher),
    profile: EmbeddingsProfile = Depends(get_embeddings_profile),
) -> ReembedOut:
    """Accept the gateway's current profile and re-embed every live document
    (all workspaces) that is not on it yet. Idempotent: a second call only
    picks up what is still missing."""
    try:
        info = await profile.client.get(force=True)
    except GatewayUnavailableError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    if body.fingerprint != info.fingerprint:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"The embeddings gateway now reports profile {info.fingerprint} ({info.model}), "
            f"not {body.fingerprint}. Review it and confirm again.",
        )
    stored, _ = await SettingsRepo(conn).get_embedding_profile()
    await profile.store(conn, info, expected=stored, reason="reembed", actor_user_id=user.id)
    target = IngestTarget.of(info)
    try:
        result = await reembed_stale(
            conn, publisher, target, trigger="admin", actor_user_id=user.id
        )
    except ReembedBusyError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "A re-embed is already running.") from exc
    profile.info = info
    await profile.evaluate(conn)
    return ReembedOut(fingerprint=info.fingerprint, collection=info.collection, **result)
