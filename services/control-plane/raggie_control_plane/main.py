# SPDX-License-Identifier: Apache-2.0

"""Raggie control plane — FastAPI application entrypoint.

Wires the Postgres pool and applies migrations on boot, then mounts the
admin/management API routers (orgs/teams/workspaces/users/RBAC/settings/
onboarding, documents, SSO/SCIM, …).
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.middleware.base import RequestResponseEndpoint

from raggie_control_plane.api.admin import router as admin_router
from raggie_control_plane.api.ai_config import router as ai_config_router
from raggie_control_plane.api.analytics import router as analytics_router
from raggie_control_plane.api.auth import router as auth_router
from raggie_control_plane.api.branding import router as branding_router
from raggie_control_plane.api.client_ip import is_https
from raggie_control_plane.api.directory import router as directory_router
from raggie_control_plane.api.documents import router as documents_router
from raggie_control_plane.api.embeddings import router as embeddings_router
from raggie_control_plane.api.integrations import router as integrations_router
from raggie_control_plane.api.onboarding import router as onboarding_router
from raggie_control_plane.api.qdrant_viz import router as qdrant_viz_router
from raggie_control_plane.api.scheduled_tasks import router as scheduled_tasks_router
from raggie_control_plane.api.scim import router as scim_router
from raggie_control_plane.api.skills import router as skills_router
from raggie_control_plane.api.sso import router as sso_router
from raggie_control_plane.api.updates import router as updates_router
from raggie_control_plane.api.workspaces import router as workspaces_router
from raggie_control_plane.auth.setup_token import ensure_setup_token
from raggie_control_plane.config import (
    InsecureConfigurationError,
    api_docs_enabled,
    settings,
    validate_runtime_secrets,
)
from raggie_control_plane.db.migrate import apply_migrations, pending_migrations
from raggie_control_plane.db.pool import create_pool
from raggie_control_plane.embeddings_profile import EmbeddingsProfile
from raggie_control_plane.infra.objectstore import MinioObjectStore
from raggie_control_plane.infra.publisher import RedisEventPublisher
from raggie_control_plane.infra.redisconn import create_redis
from raggie_control_plane.logging import configure_logging

_DOCS_ENABLED = api_docs_enabled(settings)
_DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")
# Boot waits this long for the first embedding-profile check, then carries on
# and keeps retrying in the background (the gateway may still be loading).
_EMBEDDINGS_BOOT_TIMEOUT_SECONDS = 10.0

log = logging.getLogger("control-plane")

# Refuse an unsafe configuration while uvicorn imports the app: an exception
# from the lifespan would print a Starlette traceback before the reason.
try:
    validate_runtime_secrets(settings)
except InsecureConfigurationError as exc:
    sys.exit(f"control-plane: {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging(settings.control_plane_log_level)
    # Fail fast, before touching any datastore, on default/weak secrets (again:
    # settings may have changed since import).
    validate_runtime_secrets(settings)
    pool = await create_pool()
    app.state.pool = pool
    if settings.run_migrations_on_boot:
        async with pool.acquire() as conn:
            applied = await apply_migrations(conn, settings.migrations_dir)
        if applied:
            log.info("applied %d migration(s): %s", len(applied), ", ".join(applied))
    async with pool.acquire() as conn:
        await ensure_setup_token(conn)
    # Lazy clients (no connection until first use). One Redis client (URL or
    # Sentinel) shared by every Redis user: event publisher, login lockout.
    redis_conn = create_redis(settings)
    app.state.redis = redis_conn.client
    app.state.event_publisher = RedisEventPublisher(app.state.redis)
    app.state.object_store = MinioObjectStore(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_root_user,
        secret_key=settings.minio_root_password,
        bucket=settings.minio_bucket,
        secure=settings.minio_use_ssl,
    )
    profile = EmbeddingsProfile.from_settings(settings)
    app.state.embeddings_profile = profile
    try:
        ok = await asyncio.wait_for(
            profile.refresh(pool, app.state.event_publisher),
            timeout=_EMBEDDINGS_BOOT_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        log.warning("embedding profile check is slow; continuing it in the background")
        ok = False
    reconciler = asyncio.create_task(
        profile.run(pool, app.state.event_publisher, last_ok=ok), name="embeddings-profile"
    )
    try:
        yield
    finally:
        reconciler.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await reconciler
        await redis_conn.aclose()
        await pool.close()


app = FastAPI(
    title="Raggie Control Plane",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if _DOCS_ENABLED else None,
    redoc_url="/redoc" if _DOCS_ENABLED else None,
    openapi_url="/openapi.json" if _DOCS_ENABLED else None,
)
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(onboarding_router)
app.include_router(documents_router)
app.include_router(embeddings_router)
app.include_router(workspaces_router)
app.include_router(analytics_router)
app.include_router(integrations_router)
app.include_router(qdrant_viz_router)
app.include_router(branding_router)
app.include_router(ai_config_router)
app.include_router(directory_router)
app.include_router(updates_router)
app.include_router(sso_router)
app.include_router(scim_router)
app.include_router(skills_router)
app.include_router(scheduled_tasks_router)


@app.middleware("http")
async def security_headers(request: Request, call_next: RequestResponseEndpoint) -> Response:
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
    if settings.is_development:
        return response
    # The JSON API never renders HTML; the Swagger UI (only when explicitly
    # exposed) needs its CDN assets, so it is exempt from the strict CSP.
    if not request.url.path.startswith(_DOCS_PATHS):
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
        )
    if is_https(request):
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "control-plane"}


@app.get("/readyz")
async def readyz() -> Response:
    pool = getattr(app.state, "pool", None)
    if pool is None:
        return Response(
            content='{"status":"no pool"}', status_code=503, media_type="application/json"
        )
    try:
        async with pool.acquire() as conn:
            pending = await pending_migrations(conn, settings.migrations_dir)
    except Exception:  # noqa: BLE001 — readiness must never raise
        return Response(
            content='{"status":"db unreachable"}',
            status_code=503,
            media_type="application/json",
        )
    if pending:
        # Code is newer than the schema (migration Job not run / still running):
        # take no traffic rather than fail on missing columns.
        return Response(
            content='{"status":"schema behind bundled migrations"}',
            status_code=503,
            media_type="application/json",
        )
    profile: EmbeddingsProfile | None = getattr(app.state, "embeddings_profile", None)
    if profile is None:
        return Response(content='{"status":"ready"}', media_type="application/json")
    # An unknown profile or a block_ingest mismatch keeps the replica in
    # rotation ("degraded": admin and chat work, uploads are refused); only
    # EMBEDDINGS_FINGERPRINT_POLICY=refuse_boot turns a mismatch into a 503.
    status_code, body = profile.readiness()
    return Response(
        content=json.dumps(body), status_code=status_code, media_type="application/json"
    )


@app.get("/metrics")
async def metrics(request: Request) -> Response:
    if settings.metrics_token:
        presented = request.headers.get("authorization", "")
        expected = f"Bearer {settings.metrics_token}"
        if not hmac.compare_digest(presented.encode(), expected.encode()):
            return Response(
                content='{"detail":"metrics token required"}',
                status_code=401,
                media_type="application/json",
                headers={"WWW-Authenticate": "Bearer"},
            )
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
