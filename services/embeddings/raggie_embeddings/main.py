# SPDX-License-Identifier: Apache-2.0

"""Embeddings gateway — the single internal embedding service.

Edge and workers always call this service; it either runs the models locally
(fastembed/ONNX, default: no data leaves the server) or proxies dense
embeddings / reranking to a cloud upstream. BM25 sparse is always local.

Endpoints (under /v1, Bearer $INTERNAL_API_SECRET when auth is required):
  POST /v1/embeddings  — dense, OpenAI-compatible. `input_type` ("query"|"passage",
                         default "passage") selects prefixes / extra JSON.
  POST /v1/sparse      — batch BM25 sparse vectors for documents (indexing).
  POST /v1/query       — dense + sparse for ONE query (edge hybrid retrieval).
  POST /v1/rerank      — cross-encoder reranking (identity order on failure).
  GET  /v1/info        — active profile: model, dim, fingerprint, collection, egress.
Every dense response carries the profile's `collection` and `fingerprint`; the
contract lives in contracts/embeddings_gateway.schema.json.

Readiness: a startup probe embeds one text and requires len == EMBEDDING_DIM;
until it passes /readyz is 503 with the reason, re-probed periodically.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from raggie_embeddings.config import Settings, settings
from raggie_embeddings.logging import configure_logging
from raggie_embeddings.providers.auth import internal_auth
from raggie_embeddings.providers.cache import QueryCache
from raggie_embeddings.providers.fingerprint import Profile, collection_name, fingerprint
from raggie_embeddings.providers.local import LocalDense, LocalReranker, LocalSparse
from raggie_embeddings.providers.openai_compat import (
    InputType,
    OpenAICompatDense,
    UpstreamError,
    host_of,
)
from raggie_embeddings.providers.redisconn import create_redis
from raggie_embeddings.providers.rerank_remote import RemoteReranker
from raggie_embeddings.schemas import (
    EgressInfo,
    EmbeddingItem,
    EmbeddingsRequest,
    EmbeddingsResponse,
    ErrorResponse,
    InfoResponse,
    QueryRequest,
    QueryResponse,
    RerankerInfo,
    RerankRequest,
    RerankResponse,
    RerankResult,
    SparseItem,
    SparseRequest,
    SparseResponse,
    SparseVector,
    Usage,
)

logger = logging.getLogger("raggie.embeddings")

_PROBE_TEXT = "raggie readiness probe"


class Gateway:
    """Runtime state: the active providers plus the readiness probe result."""

    def __init__(
        self,
        cfg: Settings,
        *,
        dense: Any,
        sparse: LocalSparse,
        reranker: LocalReranker | RemoteReranker | None,
        cache: QueryCache | None,
    ) -> None:
        self.cfg = cfg
        self.profile = Profile.from_settings(cfg)
        self.fingerprint = fingerprint(self.profile)
        self.collection = collection_name(self.profile)
        self.dense = dense
        self.sparse = sparse
        self.reranker = reranker
        self.cache = cache
        self.status = "loading"
        self.reason: str | None = None

    async def embed(self, texts: list[str], input_type: InputType) -> list[list[float]]:
        if input_type != "query" or self.cache is None:
            return await self.dense.embed(texts, input_type)
        vectors: list[list[float] | None] = [await self.cache.get(t) for t in texts]
        missing = [i for i, v in enumerate(vectors) if v is None]
        if missing:
            fresh = await self.dense.embed([texts[i] for i in missing], "query")
            for i, vector in zip(missing, fresh, strict=True):
                vectors[i] = vector
                await self.cache.set(texts[i], vector)
        return [v for v in vectors if v is not None]

    async def probe(self) -> bool:
        try:
            vectors = await self.dense.embed([_PROBE_TEXT], "query")
        except UpstreamError as exc:
            self.status, self.reason = "not_ready", exc.detail
            return False
        except Exception as exc:  # noqa: BLE001 — any failure keeps us unready
            self.status, self.reason = "not_ready", f"probe failed: {type(exc).__name__}"
            logger.exception("embedding probe failed")
            return False
        got = len(vectors[0]) if vectors else 0
        if got != self.cfg.embedding_dim:
            self.status = "not_ready"
            self.reason = (
                f"dimension mismatch: model returned {got}-dimensional vectors; "
                f"EMBEDDING_DIM={self.cfg.embedding_dim}"
            )
            return False
        self.status, self.reason = "ready", None
        return True

    async def probe_until_ready(self) -> None:
        while not await self.probe():
            logger.warning("embeddings not ready: %s", self.reason)
            await asyncio.sleep(self.cfg.embeddings_probe_interval_seconds)
        logger.info(
            "embeddings ready: collection=%s fingerprint=%s", self.collection, self.fingerprint
        )

    def info(self) -> InfoResponse:
        cfg = self.cfg
        rerank_provider = cfg.effective_reranker_provider
        return InfoResponse(
            provider=cfg.embeddings_provider,
            model=cfg.embeddings_model,
            dim=cfg.embedding_dim,
            fingerprint=self.fingerprint,
            collection=self.collection,
            sparse_model=cfg.sparse_model if cfg.sparse_enabled else None,
            reranker=RerankerInfo(
                provider=rerank_provider,
                model=None if rerank_provider == "none" else cfg.reranker_model,
            ),
            egress=EgressInfo(
                dense_host=getattr(self.dense, "host", None),
                rerank_host=getattr(self.reranker, "host", None),
            ),
        )


def _upstream_error(exc: UpstreamError) -> JSONResponse:
    headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after is not None else None
    return JSONResponse(
        ErrorResponse(detail=exc.detail).model_dump(), status_code=exc.status_code, headers=headers
    )


def _gateway(request: Request) -> Gateway:
    return request.app.state.gateway


def create_app(
    cfg: Settings,
    *,
    dense: Any | None = None,
    sparse: LocalSparse | None = None,
    reranker: LocalReranker | RemoteReranker | None = None,
    redis: Any | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> FastAPI:
    """Build the gateway. Keyword overrides inject providers (tests, tooling);
    anything not given is constructed from ``cfg`` at startup."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(cfg.embeddings_log_level)
        cfg.validate_for_boot()
        if cfg.is_cloud_dense and not cfg.embeddings_upstream_api_key:
            # Valid for a keyless self-hosted upstream (TEI, vLLM); a hosted API
            # will answer 401, which /readyz then reports.
            logger.warning(
                "EMBEDDINGS_UPSTREAM_API_KEY is empty: requests to %s carry no "
                "Authorization header (fine for a keyless TEI/vLLM; otherwise set it "
                "in .env.embeddings)",
                host_of(cfg.embeddings_upstream_base_url) or "-",
            )
        rerank_provider = cfg.effective_reranker_provider
        needs_http = cfg.is_cloud_dense or rerank_provider in ("cohere", "voyage", "tei")
        client = http_client
        owns_client = client is None and needs_http
        if owns_client:
            # Every call passes its own per-kind timeout; this default only
            # bounds anything that does not.
            client = httpx.AsyncClient(
                timeout=httpx.Timeout(cfg.embeddings_passage_timeout_seconds),
                limits=httpx.Limits(
                    max_connections=cfg.embeddings_upstream_concurrency + 4,
                    max_keepalive_connections=cfg.embeddings_upstream_concurrency + 4,
                ),
            )

        dense_provider = dense
        if dense_provider is None:
            if cfg.is_cloud_dense:
                # Cloud mode never loads the local dense model.
                dense_provider = OpenAICompatDense(cfg, client)
            else:
                dense_provider = await asyncio.to_thread(LocalDense.load, cfg)
        sparse_provider = sparse if sparse is not None else LocalSparse.load(cfg)

        rerank_impl = reranker
        background: list[asyncio.Task] = []
        if rerank_impl is None and rerank_provider == "local":
            rerank_impl = LocalReranker(cfg)
            background.append(asyncio.create_task(rerank_impl.load_in_background()))
        elif rerank_impl is None and rerank_provider in ("cohere", "voyage", "tei"):
            rerank_impl = RemoteReranker(cfg, client)
        if rerank_provider == "none":
            rerank_impl = None

        redis_client = redis
        redis_conn = None
        if redis_client is None and cfg.cache_configured:
            # Sentinel (HA) or URL, exactly like the other services' Redis clients.
            redis_conn = create_redis(cfg)
            redis_client = redis_conn.client

        gateway = Gateway(
            cfg, dense=dense_provider, sparse=sparse_provider, reranker=rerank_impl, cache=None
        )
        if redis_client is not None and cfg.embeddings_cache_enabled:
            gateway.cache = QueryCache(
                redis_client,
                fingerprint=gateway.fingerprint,
                ttl_seconds=cfg.embeddings_cache_ttl_seconds,
                timeout_seconds=cfg.embeddings_cache_timeout_seconds,
            )
        app.state.gateway = gateway
        egress = gateway.info().egress
        # The JSON log formatter keeps only the message, so the values go inline.
        logger.info(
            "embeddings gateway starting: provider=%s model=%s dim=%d collection=%s "
            "fingerprint=%s reranker=%s egress_dense_host=%s egress_rerank_host=%s",
            cfg.embeddings_provider,
            cfg.embeddings_model,
            cfg.embedding_dim,
            gateway.collection,
            gateway.fingerprint,
            rerank_provider,
            egress.dense_host or "-",
            egress.rerank_host or "-",
        )
        background.append(asyncio.create_task(gateway.probe_until_ready()))
        try:
            yield
        finally:
            for task in background:
                task.cancel()
            for task in background:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
            if owns_client and client is not None:
                await client.aclose()
            if redis_conn is not None:
                await redis_conn.aclose()

    app = FastAPI(title="Raggie Embeddings", version="0.3.0", lifespan=lifespan)
    v1 = APIRouter(prefix="/v1", dependencies=[Depends(internal_auth(cfg))])
    errors = {
        401: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    }

    @v1.post("/embeddings", response_model=EmbeddingsResponse, responses=errors)
    async def create_embeddings(body: EmbeddingsRequest, request: Request):
        gw = _gateway(request)
        texts = [body.input] if isinstance(body.input, str) else list(body.input)
        input_type: InputType = "query" if body.input_type == "query" else "passage"
        try:
            vectors = await gw.embed(texts, input_type)
        except UpstreamError as exc:
            return _upstream_error(exc)
        approx_tokens = sum(len(t.split()) for t in texts)
        return EmbeddingsResponse(
            data=[EmbeddingItem(index=i, embedding=v) for i, v in enumerate(vectors)],
            model=cfg.embeddings_model,
            usage=Usage(prompt_tokens=approx_tokens, total_tokens=approx_tokens),
            collection=gw.collection,
            fingerprint=gw.fingerprint,
        )

    @v1.post("/sparse", response_model=SparseResponse)
    async def create_sparse(body: SparseRequest, request: Request) -> SparseResponse:
        texts = [body.input] if isinstance(body.input, str) else list(body.input)
        if not texts:
            return SparseResponse(data=[])
        vectors = await _gateway(request).sparse.embed_documents(texts)
        return SparseResponse(data=[SparseItem(index=i, **v) for i, v in enumerate(vectors)])

    @v1.post("/query", response_model=QueryResponse, responses=errors)
    async def embed_query(body: QueryRequest, request: Request):
        gw = _gateway(request)
        try:
            dense_vec, sparse_vec = await asyncio.gather(
                gw.embed([body.query], "query"), gw.sparse.embed_query(body.query)
            )
        except UpstreamError as exc:
            return _upstream_error(exc)
        return QueryResponse(
            dense=dense_vec[0],
            sparse=SparseVector(**sparse_vec),
            collection=gw.collection,
            fingerprint=gw.fingerprint,
        )

    @v1.post("/rerank", response_model=RerankResponse)
    async def rerank(body: RerankRequest, request: Request) -> RerankResponse:
        """Reorder documents best-first (truncated to top_n). While loading,
        disabled or failing, returns the identity order so the edge keeps the
        fused ranking."""
        n = len(body.documents)
        if n == 0:
            return RerankResponse(results=[])
        identity = [float(n - i) for i in range(n)]
        impl = _gateway(request).reranker
        scores = identity
        if impl is not None:
            try:
                scores = await impl.rerank(body.query, body.documents)
            except Exception as exc:  # noqa: BLE001 — fail open, never fail the answer
                logger.warning("rerank unavailable (%s); identity order", exc)
                scores = identity
        order = sorted(range(n), key=lambda i: scores[i], reverse=True)
        if body.top_n:
            order = order[: body.top_n]
        return RerankResponse(results=[RerankResult(index=i, score=scores[i]) for i in order])

    @v1.get("/info", response_model=InfoResponse)
    async def info(request: Request) -> InfoResponse:
        return _gateway(request).info()

    app.include_router(v1)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "service": "embeddings"}

    @app.get("/readyz")
    async def readyz(request: Request) -> JSONResponse:
        gw: Gateway | None = getattr(request.app.state, "gateway", None)
        if gw is None or gw.status == "loading":
            return JSONResponse({"status": "loading"}, status_code=503)
        if gw.status != "ready":
            return JSONResponse({"status": gw.status, "reason": gw.reason}, status_code=503)
        return JSONResponse({"status": "ready"})

    @app.get("/metrics")
    async def metrics() -> Response:
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app(settings)
