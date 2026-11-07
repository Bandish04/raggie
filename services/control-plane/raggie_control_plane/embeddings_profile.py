# SPDX-License-Identifier: Apache-2.0

"""The embeddings gateway's active profile, reconciled with the indexed documents.

The gateway (services/embeddings) owns the embedding model. Its
``GET {EMBEDDINGS_BASE_URL}/info`` names the active profile — provider, model,
dim, fingerprint and the Qdrant collection those vectors belong in
(contracts/embeddings_gateway.schema.json). The control plane never derives a
collection itself: every upload, re-index and retry targets the collection the
gateway names, and each document records the fingerprint it is indexed with
(``documents.embedding_fingerprint``).

``system_settings.embedding_fingerprint`` is the profile the platform accepted.
When the gateway reports another fingerprint while live documents are indexed
under a different one, the vector spaces no longer match and
EMBEDDINGS_FINGERPRINT_POLICY decides:

* ``block_ingest`` (default) — keep serving, refuse uploads / re-indexes with
  409 until a platform admin re-embeds; /readyz stays 200 ("degraded").
* ``refuse_boot`` — as block_ingest, and /readyz answers 503.
* ``auto_reindex`` — re-embed every live document into the new collection, but
  only when EMBEDDINGS_REEMBED_CONFIRM equals the NEW fingerprint (an explicit
  acknowledgement of the cost); otherwise as block_ingest.

With no documents on another profile, a new profile is simply adopted. An
unreachable gateway never stops the control plane: reconciliation retries in
the background and ingestion answers 503 until the profile is known. Every
change of the stored profile (model, provider or egress hosts) is audited. The
old collection is never dropped automatically.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from raggie_control_plane.config import Settings
from raggie_control_plane.db.repositories import AuditRepo, DocumentRepo, SettingsRepo
from raggie_control_plane.infra.publisher import DOCUMENT_UPLOADED, EventPublisher
from raggie_control_plane.models import Document, Workspace

log = logging.getLogger("control-plane.embeddings")

# The legacy local profile (intfloat/multilingual-e5-large, 1024-d, E5 prefixes)
# keeps the pre-gateway collection name; migration 0026 backfills it.
LEGACY_FINGERPRINT = "2872ae6a"
LEGACY_COLLECTION = "raggie_chunks_d1024"

AUDIT_PROFILE_CHANGED = "embedding.profile_changed"
AUDIT_REEMBED_STARTED = "embedding.reembed_started"

# One re-embed (or restore re-index) at a time across replicas: a lease row in
# system_settings (0030), refreshed while the run lasts. Not a session advisory
# lock: behind a transaction pooler lock and unlock can reach different backends.
REEMBED_LEASE_SECONDS = 300.0

_FINGERPRINT_PATTERN = r"^[0-9a-f]{8}$"
_COLLECTION_PATTERN = r"^raggie_chunks_d[0-9]+(_[0-9a-f]{8})?$"
_RETRY_MIN_SECONDS = 2.0
_INGEST_RETRY_AFTER_SECONDS = 30


class RerankerInfo(BaseModel):
    provider: str
    model: str | None = None


class EgressInfo(BaseModel):
    """Hostnames document text is sent to (None = stays on this server)."""

    dense_host: str | None = None
    rerank_host: str | None = None


class EmbeddingsInfo(BaseModel):
    """GET /v1/info. Unknown fields are ignored (the contract is additive); the
    collection is validated because it ends up in Qdrant URL paths."""

    model_config = ConfigDict(extra="ignore")

    provider: str
    model: str
    dim: int = Field(gt=0)
    fingerprint: str = Field(pattern=_FINGERPRINT_PATTERN)
    collection: str = Field(pattern=_COLLECTION_PATTERN)
    sparse_model: str | None = None
    reranker: RerankerInfo
    egress: EgressInfo


class GatewayUnavailableError(RuntimeError):
    """The gateway did not return a usable profile (message is log/UI-safe)."""


class GatewayInfoClient:
    """GET {base_url}/info, reusing an answer for ``ttl_seconds``."""

    def __init__(
        self,
        base_url: str,
        *,
        secret: str = "",
        ttl_seconds: float = 60.0,
        timeout_seconds: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._secret = secret
        self._ttl = ttl_seconds
        self._timeout = timeout_seconds
        self._clock = clock
        self._cached: EmbeddingsInfo | None = None
        self._fetched_at = 0.0

    async def get(self, *, force: bool = False) -> EmbeddingsInfo:
        if not force and self._cached is not None and self._clock() - self._fetched_at < self._ttl:
            return self._cached
        info = await self._fetch()
        self._cached, self._fetched_at = info, self._clock()
        return info

    async def _fetch(self) -> EmbeddingsInfo:
        headers = {"Authorization": f"Bearer {self._secret}"} if self._secret else {}
        try:
            async with httpx.AsyncClient(timeout=self._timeout, headers=headers) as client:
                resp = await client.get(f"{self.base_url}/info")
        except httpx.HTTPError as exc:
            raise GatewayUnavailableError(
                f"embeddings gateway unreachable ({type(exc).__name__})"
            ) from exc
        if resp.status_code != 200:
            raise GatewayUnavailableError(
                f"embeddings gateway answered HTTP {resp.status_code} on /info"
            )
        try:
            return EmbeddingsInfo.model_validate(resp.json())
        except (ValueError, ValidationError) as exc:
            raise GatewayUnavailableError(
                "embeddings gateway returned an invalid /info body"
            ) from exc


@dataclass(frozen=True)
class IngestTarget:
    """Where (and with which profile) a document is to be embedded."""

    collection: str
    fingerprint: str
    dim: int

    @classmethod
    def of(cls, info: EmbeddingsInfo) -> IngestTarget:
        return cls(info.collection, info.fingerprint, info.dim)


def uploaded_event(doc: Document, target: IngestTarget) -> dict[str, Any]:
    """raggie.document.uploaded payload (contracts/events.md). ``collection`` and
    ``embedding_fingerprint`` are authoritative; ``embedding_dim`` stays for
    workers that predate them."""
    return {
        "document_id": str(doc.id),
        "workspace_id": str(doc.workspace_id),
        "filename": doc.filename,
        "object_key": doc.object_key,
        "embedding_dim": target.dim,
        "collection": target.collection,
        "embedding_fingerprint": target.fingerprint,
    }


async def _rearm(
    repo: DocumentRepo, publisher: EventPublisher, doc: Document, target: IngestTarget
) -> None:
    await repo.reset_for_reindex(doc.id, target.collection, target.fingerprint)
    await publisher.publish(DOCUMENT_UPLOADED, uploaded_event(doc, target))


async def reindex_workspace(
    conn: asyncpg.Connection,
    publisher: EventPublisher,
    workspace: Workspace,
    target: IngestTarget,
    *,
    keep_alive: Callable[[], Awaitable[None]] | None = None,
) -> dict[str, int]:
    """Re-arm and re-publish document.uploaded for every live document of a
    workspace that still has its raw file, pointing it at ``target``. Point ids
    are deterministic, so re-runs overwrite cleanly. Returns {reindexed, skipped}."""
    repo = DocumentRepo(conn)
    reindexed = 0
    skipped = 0
    for doc in await repo.list_live_by_workspace(workspace.id):
        if not doc.object_key:
            skipped += 1  # no raw file retained → cannot re-ingest
            continue
        if keep_alive is not None:
            await keep_alive()
        await _rearm(repo, publisher, doc, target)
        reindexed += 1
    return {"reindexed": reindexed, "skipped": skipped}


class ReembedBusyError(RuntimeError):
    """Another replica / request is already re-embedding."""


class ReembedLease:
    """The held re-embed lease. ``keep_alive`` refreshes it at most every third
    of its lifetime, and raises ReembedBusyError once it was lost."""

    def __init__(self, conn: asyncpg.Connection, owner: str) -> None:
        self._repo = SettingsRepo(conn)
        self.owner = owner
        self._refreshed = time.monotonic()

    async def keep_alive(self) -> None:
        if time.monotonic() - self._refreshed < REEMBED_LEASE_SECONDS / 3:
            return
        if not await self._repo.refresh_reembed_lease(self.owner, REEMBED_LEASE_SECONDS):
            raise ReembedBusyError("the re-embed lease expired and another run took over")
        self._refreshed = time.monotonic()


@asynccontextmanager
async def reembed_lease(conn: asyncpg.Connection) -> AsyncIterator[ReembedLease]:
    """Hold the platform-wide re-embed lease for the block; raises
    ReembedBusyError when another run holds it."""
    owner = uuid4().hex
    repo = SettingsRepo(conn)
    if not await repo.acquire_reembed_lease(owner, REEMBED_LEASE_SECONDS):
        raise ReembedBusyError("a re-embed is already running")
    try:
        yield ReembedLease(conn, owner)
    finally:
        await repo.release_reembed_lease(owner)


async def reembed_stale(
    conn: asyncpg.Connection,
    publisher: EventPublisher,
    target: IngestTarget,
    *,
    trigger: str,
    actor_user_id: UUID | None = None,
) -> dict[str, int]:
    """Re-embed every live document, in every workspace, that is not yet on
    ``target`` — the same re-arm + document.uploaded path as a workspace
    re-index. Documents already on the target are left alone, so an interrupted
    run resumes without paying twice. One run at a time, platform-wide (raises
    ReembedBusyError otherwise); audited when anything was re-published."""
    async with reembed_lease(conn) as lease:
        repo = DocumentRepo(conn)
        reembedded = 0
        skipped = 0
        workspaces: set[UUID] = set()
        for doc in await repo.list_live_off_fingerprint(target.fingerprint):
            if not doc.object_key:
                skipped += 1  # no raw file retained → cannot re-ingest
                continue
            await lease.keep_alive()
            await _rearm(repo, publisher, doc, target)
            reembedded += 1
            workspaces.add(doc.workspace_id)
    total = {"reembedded": reembedded, "skipped": skipped, "workspaces": len(workspaces)}
    if reembedded:
        await AuditRepo(conn).record(
            AUDIT_REEMBED_STARTED,
            actor_user_id=actor_user_id,
            target=target.fingerprint,
            metadata={
                "trigger": trigger,
                "fingerprint": target.fingerprint,
                "collection": target.collection,
                **total,
            },
        )
        log.info("re-embedding %d document(s) into %s (%s)", reembedded, target.collection, trigger)
    return total


class IngestBlockedError(Exception):
    """Ingestion is refused; ``detail`` is shown to the admin as is."""

    def __init__(self, status_code: int, detail: str, retry_after: int | None = None) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.retry_after = retry_after


class EmbeddingsProfile:
    """Per-replica view of the gateway profile vs. the indexed documents.

    ``run`` keeps it fresh in the background; request handlers only read it
    (``ingest_target`` re-checks the database when it would refuse, so a
    re-embed done on another replica unblocks this one immediately)."""

    def __init__(
        self,
        client: GatewayInfoClient,
        *,
        policy: str = "block_ingest",
        reembed_confirm: str = "",
        refresh_seconds: float = 60.0,
    ) -> None:
        self.client = client
        self.policy = policy
        self.reembed_confirm = reembed_confirm
        self.refresh_seconds = refresh_seconds
        self.info: EmbeddingsInfo | None = None
        self.stored_fingerprint: str | None = None
        self.mismatch = False
        self.checked_at: datetime | None = None
        self.last_error: str | None = None

    @classmethod
    def from_settings(cls, cfg: Settings) -> EmbeddingsProfile:
        client = GatewayInfoClient(
            cfg.embeddings_base_url,
            secret=cfg.internal_api_secret,
            ttl_seconds=cfg.embeddings_info_ttl_seconds,
        )
        return cls(
            client,
            policy=cfg.embeddings_fingerprint_policy,
            reembed_confirm=cfg.embeddings_reembed_confirm,
            refresh_seconds=cfg.embeddings_info_ttl_seconds,
        )

    # ── Read side ─────────────────────────────────────────────────────────────
    @property
    def status(self) -> str:
        if self.info is None:
            return "unknown"
        return "mismatch" if self.mismatch else "ok"

    @property
    def active_collection(self) -> str | None:
        return self.info.collection if self.info else None

    def blocked_reason(self) -> IngestBlockedError | None:
        if self.info is None:
            return IngestBlockedError(
                503,
                "The embedding profile is not known yet: the embeddings gateway has not "
                "answered. Uploads resume automatically once it does.",
                retry_after=_INGEST_RETRY_AFTER_SECONDS,
            )
        if self.mismatch:
            new = self.info.fingerprint
            return IngestBlockedError(
                409,
                f"The embeddings gateway now uses a different embedding profile "
                f"({self.info.model}, fingerprint {new}) than the indexed documents "
                f"(fingerprint {self.stored_fingerprint or 'unknown'}). New documents are "
                "refused until the existing ones are re-embedded: Admin → AI → Embeddings "
                f"→ Re-embed, or set EMBEDDINGS_FINGERPRINT_POLICY=auto_reindex with "
                f"EMBEDDINGS_REEMBED_CONFIRM={new}.",
            )
        return None

    async def ingest_target(self, conn: asyncpg.Connection) -> IngestTarget:
        """The collection + fingerprint uploads must use, or IngestBlockedError."""
        if self.mismatch:
            await self.evaluate(conn)
        if (blocked := self.blocked_reason()) is not None:
            raise blocked
        assert self.info is not None
        return IngestTarget.of(self.info)

    def readiness(self) -> tuple[int, dict[str, str]]:
        if self.mismatch:
            if self.policy == "refuse_boot":
                return 503, {
                    "status": "embedding fingerprint mismatch",
                    "embeddings": "fingerprint_mismatch",
                }
            return 200, {"status": "degraded", "embeddings": "fingerprint_mismatch"}
        if self.info is None:
            return 200, {"status": "degraded", "embeddings": "profile_unknown"}
        return 200, {"status": "ready"}

    async def evaluate(self, conn: asyncpg.Connection) -> None:
        """Recompute the mismatch from the database (no writes): the gateway's
        fingerprint differs from the accepted one AND live documents are indexed
        under another profile."""
        self.stored_fingerprint, _ = await SettingsRepo(conn).get_embedding_profile()
        mismatch = False
        if self.info is not None and self.stored_fingerprint != self.info.fingerprint:
            off = await DocumentRepo(conn).count_live_off_fingerprint(self.info.fingerprint)
            mismatch = off > 0
        if mismatch and not self.mismatch:
            log.warning(
                "embedding fingerprint mismatch: gateway %s, documents indexed under %s; "
                "policy %s — ingestion is blocked until the documents are re-embedded",
                self.info.fingerprint if self.info else None,
                self.stored_fingerprint,
                self.policy,
            )
        self.mismatch = mismatch

    # ── Write side (boot + background) ────────────────────────────────────────
    async def reconcile(self, conn: asyncpg.Connection, publisher: EventPublisher) -> None:
        """Fetch the gateway profile and reconcile it with the stored one (see
        the module docstring). Raises GatewayUnavailableError."""
        info = await self.client.get(force=True)
        await self._accept_if_safe(conn, publisher, info)
        self.info = info
        await self.evaluate(conn)
        self.checked_at = datetime.now(UTC)
        self.last_error = None

    async def _accept_if_safe(
        self, conn: asyncpg.Connection, publisher: EventPublisher, info: EmbeddingsInfo
    ) -> None:
        stored_fp, stored_profile = await SettingsRepo(conn).get_embedding_profile()
        if stored_fp == info.fingerprint:
            if stored_profile != info.model_dump():
                await self.store(conn, info, expected=stored_fp, reason="profile_updated")
        elif await DocumentRepo(conn).count_live_off_fingerprint(info.fingerprint) == 0:
            reason = "initial" if stored_fp is None else "adopted"
            await self.store(conn, info, expected=stored_fp, reason=reason)
        elif self.policy == "auto_reindex" and self.reembed_confirm == info.fingerprint:
            await self.store(conn, info, expected=stored_fp, reason="auto_reindex")
        if self.policy == "auto_reindex" and self.reembed_confirm == info.fingerprint:
            # Also resumes a re-embed that was interrupted after the switch.
            try:
                await reembed_stale(conn, publisher, IngestTarget.of(info), trigger="auto_reindex")
            except ReembedBusyError:
                log.info("auto re-embed already running on another replica")

    async def store(
        self,
        conn: asyncpg.Connection,
        info: EmbeddingsInfo,
        *,
        expected: str | None,
        reason: str,
        actor_user_id: UUID | None = None,
    ) -> bool:
        """Persist ``info`` as the accepted profile (compare-and-set against
        ``expected``) and audit the change. True when this call changed it."""
        async with conn.transaction():
            changed = await SettingsRepo(conn).store_embedding_profile(
                info.fingerprint, info.model_dump(), expected=expected
            )
            if changed:
                await AuditRepo(conn).record(
                    AUDIT_PROFILE_CHANGED,
                    actor_user_id=actor_user_id,
                    target=info.fingerprint,
                    metadata=_audit_metadata(info, previous=expected, reason=reason),
                )
        if changed:
            log.info(
                "embedding profile %s stored (%s): provider=%s model=%s dense_host=%s "
                "rerank_host=%s",
                info.fingerprint,
                reason,
                info.provider,
                info.model,
                info.egress.dense_host,
                info.egress.rerank_host,
            )
        return changed

    async def refresh(self, pool: asyncpg.Pool, publisher: EventPublisher) -> bool:
        """One reconciliation; never raises. True on success."""
        try:
            async with pool.acquire() as conn:
                await self.reconcile(conn, publisher)
        except GatewayUnavailableError as exc:
            if self.last_error != str(exc):
                log.warning("%s; retrying in the background", exc)
            self.last_error = str(exc)
            return False
        except Exception:  # noqa: BLE001 — the loop must survive anything
            log.exception("embedding profile reconciliation failed")
            self.last_error = "reconciliation failed (see control-plane logs)"
            return False
        return True

    async def run(
        self, pool: asyncpg.Pool, publisher: EventPublisher, *, last_ok: bool = False
    ) -> None:
        """Background loop: re-check every ``refresh_seconds``; while the gateway
        is unreachable retry with exponential backoff (2s → refresh_seconds)."""
        backoff = _RETRY_MIN_SECONDS
        ok = last_ok
        while True:
            if ok:
                backoff = _RETRY_MIN_SECONDS
                await asyncio.sleep(self.refresh_seconds)
            else:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self.refresh_seconds)
            ok = await self.refresh(pool, publisher)


def _audit_metadata(info: EmbeddingsInfo, *, previous: str | None, reason: str) -> dict:
    # Never any credential: /info carries none, and only hostnames are recorded.
    return {
        "reason": reason,
        "previous_fingerprint": previous,
        "fingerprint": info.fingerprint,
        "provider": info.provider,
        "model": info.model,
        "dim": info.dim,
        "collection": info.collection,
        "sparse_model": info.sparse_model,
        "reranker_provider": info.reranker.provider,
        "reranker_model": info.reranker.model,
        "dense_host": info.egress.dense_host,
        "rerank_host": info.egress.rerank_host,
    }
