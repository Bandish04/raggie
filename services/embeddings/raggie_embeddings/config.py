# SPDX-License-Identifier: Apache-2.0

"""Embeddings gateway configuration.

The service is the single internal embedding gateway: edge and workers always
talk to it, and it either runs the models locally (fastembed/ONNX, the default:
no document text leaves the server) or proxies dense embeddings / reranking to
a cloud upstream. BM25 sparse vectors are ALWAYS computed locally so hybrid
search keeps working in both modes.
"""

from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path
from typing import Any, Literal

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LEGACY_DENSE_MODEL = "intfloat/multilingual-e5-large"
LEGACY_DIM = 1024
E5_QUERY_PREFIX = "query: "
E5_PASSAGE_PREFIX = "passage: "

DenseProviderName = Literal["local", "openai_compatible"]
RerankProviderName = Literal["local", "cohere", "voyage", "tei", "none"]


DEVELOPMENT_ENVS = frozenset({"development", "dev", "local", "test", "testing"})
_SHARED_SECRET_MIN_BYTES = 32
_REMOTE_RERANKERS = frozenset({"cohere", "voyage", "tei"})

logger = logging.getLogger("raggie.embeddings.config")


class ConfigError(ValueError):
    """Static misconfiguration: the gateway refuses to boot."""


def _parse_json_object(name: str, raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{name} is not valid JSON: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ConfigError(f"{name} must be a JSON object")
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Unset means production: the INTERNAL_API_SECRET strength check applies
    # unless the operator explicitly opts into a development/test environment.
    raggie_env: str = "production"
    embeddings_port: int = 8002
    embeddings_log_level: str = "info"

    # ── dense ───────────────────────────────────────────────────────────────
    # local: fastembed ONNX on this host. openai_compatible: POST {base}/embeddings
    # on OpenAI, Jina, Mistral, Voyage, or a self-hosted TEI/vLLM/Ollama.
    embeddings_provider: DenseProviderName = "local"
    # Local: a fastembed model id. Cloud: the upstream's (versioned) model id.
    # intfloat/multilingual-e5-large is the strongest broadly-supported
    # multilingual dense model in fastembed (bge-m3 is NOT supported by fastembed).
    embeddings_model: str = LEGACY_DENSE_MODEL
    # MUST equal the vectors the model/upstream returns; the startup probe checks
    # it and /readyz stays 503 until it matches.
    embedding_dim: int = Field(default=LEGACY_DIM, gt=0)
    # Instruction prefixes. None = automatic: E5 models locally get the required
    # "query: " / "passage: " prefixes, everything else (incl. cloud) gets none.
    # Set to "" explicitly to disable.
    embeddings_query_prefix: str | None = None
    embeddings_passage_prefix: str | None = None

    embeddings_upstream_base_url: str = ""
    embeddings_upstream_api_key: str = ""
    # Provider-specific request fields as JSON objects, merged into every
    # upstream body (request) and per input type (query/passage), e.g.
    # {"dimensions": 1024} or {"input_type": "query"} / {"task": "retrieval.passage"}.
    embeddings_request_extra_json: str = ""
    embeddings_query_extra_json: str = ""
    embeddings_passage_extra_json: str = ""

    # Cloud call behaviour (one keep-alive httpx client per replica).
    embeddings_query_timeout_seconds: float = Field(default=3.0, gt=0)
    embeddings_query_retries: int = Field(default=1, ge=0)
    embeddings_passage_timeout_seconds: float = Field(default=60.0, gt=0)
    embeddings_passage_retries: int = Field(default=5, ge=0)
    embeddings_retry_backoff_base_seconds: float = Field(default=0.5, ge=0)
    embeddings_retry_backoff_max_seconds: float = Field(default=30.0, ge=0)
    # Upstream slots per replica; `query_reserved` of them only serve queries so
    # a bulk ingest can never starve the search path.
    embeddings_upstream_concurrency: int = Field(default=8, ge=1)
    embeddings_query_reserved_slots: int = Field(default=2, ge=0)
    # One upstream request carries at most this many inputs / characters.
    embeddings_upstream_batch_size: int = Field(default=64, ge=1)
    embeddings_upstream_batch_max_chars: int = Field(default=200_000, ge=1)
    # Every input is cut to this many characters before embedding.
    embeddings_max_input_chars: int = Field(default=8000, ge=1)
    # Startup probe: embed one text and require len == EMBEDDING_DIM; /readyz is
    # 503 (with the reason) and the probe repeats at this interval until it passes.
    embeddings_probe_interval_seconds: float = Field(default=30.0, gt=0)

    # ── query-embedding cache (Redis) ───────────────────────────────────────
    # Key emb:q:{fingerprint}:{sha256(normalized query)}, float32 bytes. Empty
    # URL disables it; any Redis error fails open (embed without cache).
    embeddings_cache_enabled: bool = True
    embeddings_cache_redis_url: str = Field(
        default="",
        validation_alias=AliasChoices("EMBEDDINGS_CACHE_REDIS_URL", "REDIS_URL"),
    )
    embeddings_cache_ttl_seconds: int = Field(default=86_400, ge=1)
    # Hard bound per cache call (and its socket timeouts): a down Redis costs a
    # query at most this much, then the cache is bypassed for 30s.
    embeddings_cache_timeout_seconds: float = Field(default=0.5, gt=0)
    # Same Redis settings as the edge/control-plane/workers: REDIS_PASSWORD fills
    # in when the URL carries none (and authenticates to Sentinel-managed data
    # nodes); when REDIS_SENTINEL_ADDRS (host:port,...) and REDIS_SENTINEL_MASTER
    # are both set the cache follows the Sentinel master and the URL is ignored.
    # Half-configured Sentinel = boot error.
    redis_password: str = ""
    redis_db: int = 0
    redis_sentinel_addrs: str = ""
    redis_sentinel_master: str = ""
    redis_sentinel_password: str = ""

    # ── sparse (always local) ───────────────────────────────────────────────
    # fastembed Qdrant/bm25 produces term frequencies for documents and constant
    # weights for queries; Qdrant applies IDF (the collection's sparse vector MUST
    # use modifier=IDF). sparse_language is omitted unless set.
    sparse_enabled: bool = True
    sparse_model: str = "Qdrant/bm25"
    sparse_language: str | None = None

    # ── reranker ────────────────────────────────────────────────────────────
    # local: ONNX cross-encoder, background-loaded. cohere (also Jina / vLLM
    # /rerank), voyage, tei: remote dialects. none: identity order.
    # RERANKER_ENABLED=false forces none.
    reranker_enabled: bool = True
    reranker_provider: RerankProviderName = "local"
    # Local default is Apache-2.0 (selected by scripts/bench_rerank.py); cloud:
    # the upstream's model id (e.g. rerank-v3.5, rerank-2, jina-reranker-v2-...).
    reranker_model: str = "Alibaba-NLP/gte-multilingual-reranker-base"
    reranker_upstream_url: str = ""
    reranker_upstream_api_key: str = ""
    reranker_timeout_seconds: float = Field(default=3.0, gt=0)
    reranker_max_doc_chars: int = Field(default=4000, ge=1)
    # Query/document pairs per ONNX forward pass (local). Small batches keep the
    # onnxruntime arena small: at 64, 24 long documents peak at ~2.7 GB RSS
    # with gte-multilingual-reranker-base; at 8 well under 1 GB.
    reranker_batch_size: int = Field(default=8, ge=1)

    # ── auth ────────────────────────────────────────────────────────────────
    # Require "Authorization: Bearer $INTERNAL_API_SECRET" on /v1/*. None =
    # automatic: on in cloud mode or with a remote reranker (an upstream key is
    # behind this service) and whenever INTERNAL_API_SECRET is set (every caller
    # sends it); off only for a fully local install without a secret. Turning it
    # off explicitly while an upstream key is configured refuses to boot outside
    # development.
    embeddings_require_auth: bool | None = None
    internal_api_secret: str = ""

    # onnxruntime intra-op threads per local model (dense + reranker), passed as
    # fastembed `threads`. Unset = onnxruntime default (all physical cores).
    # OMP_NUM_THREADS does NOT limit onnxruntime; size this per replica instead.
    embeddings_onnx_threads: int | None = Field(default=None, ge=1)

    # Where pinned ONNX snapshots live (baked into the -local image).
    model_cache_dir: str = Field(
        default=str(Path(tempfile.gettempdir()) / "fastembed_cache"),
        validation_alias=AliasChoices("FASTEMBED_CACHE_PATH", "MODEL_CACHE_DIR"),
    )

    @field_validator("embeddings_upstream_base_url", "reranker_upstream_url")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        return value.strip().rstrip("/")

    # ── derived ─────────────────────────────────────────────────────────────

    @property
    def is_cloud_dense(self) -> bool:
        return self.embeddings_provider == "openai_compatible"

    def _auto_e5(self) -> bool:
        return not self.is_cloud_dense and "e5" in self.embeddings_model.lower()

    @property
    def query_prefix(self) -> str:
        if self.embeddings_query_prefix is not None:
            return self.embeddings_query_prefix
        return E5_QUERY_PREFIX if self._auto_e5() else ""

    @property
    def passage_prefix(self) -> str:
        if self.embeddings_passage_prefix is not None:
            return self.embeddings_passage_prefix
        return E5_PASSAGE_PREFIX if self._auto_e5() else ""

    @property
    def request_extra(self) -> dict[str, Any]:
        return _parse_json_object(
            "EMBEDDINGS_REQUEST_EXTRA_JSON", self.embeddings_request_extra_json
        )

    @property
    def query_extra(self) -> dict[str, Any]:
        return _parse_json_object("EMBEDDINGS_QUERY_EXTRA_JSON", self.embeddings_query_extra_json)

    @property
    def passage_extra(self) -> dict[str, Any]:
        return _parse_json_object(
            "EMBEDDINGS_PASSAGE_EXTRA_JSON", self.embeddings_passage_extra_json
        )

    @property
    def effective_reranker_provider(self) -> RerankProviderName:
        return self.reranker_provider if self.reranker_enabled else "none"

    @property
    def redis_db_clamped(self) -> int:
        return min(max(self.redis_db, 0), 1024)  # same bounds as the edge

    @property
    def redis_sentinel_enabled(self) -> bool:
        return bool(self.redis_sentinel_addrs.strip()) and bool(self.redis_sentinel_master.strip())

    @property
    def cache_configured(self) -> bool:
        return self.embeddings_cache_enabled and (
            self.redis_sentinel_enabled or bool(self.embeddings_cache_redis_url.strip())
        )

    @property
    def is_remote_reranker(self) -> bool:
        return self.effective_reranker_provider in _REMOTE_RERANKERS

    @property
    def upstream_key_in_use(self) -> bool:
        """A (possibly paid) upstream credential that /v1/* would spend."""
        return (self.is_cloud_dense and bool(self.embeddings_upstream_api_key)) or (
            self.is_remote_reranker and bool(self.reranker_upstream_api_key)
        )

    @property
    def require_auth(self) -> bool:
        if self.embeddings_require_auth is not None:
            return self.embeddings_require_auth
        # Anything behind an upstream (dense or rerank) or a configured secret.
        return self.is_cloud_dense or self.is_remote_reranker or bool(self.internal_api_secret)

    def validate_for_boot(self) -> None:
        """Raise ConfigError for misconfiguration that no retry can fix."""
        # Parse every extra JSON once so a typo fails at boot, not per request.
        _ = self.request_extra, self.query_extra, self.passage_extra
        if bool(self.redis_sentinel_addrs.strip()) != bool(self.redis_sentinel_master.strip()):
            raise ConfigError(
                "REDIS_SENTINEL_ADDRS and REDIS_SENTINEL_MASTER must be set together "
                "(or both left empty to use REDIS_URL)"
            )
        if self.is_cloud_dense and not self.embeddings_upstream_base_url:
            raise ConfigError(
                "EMBEDDINGS_PROVIDER=openai_compatible needs EMBEDDINGS_UPSTREAM_BASE_URL"
            )
        if self.is_remote_reranker and not self.reranker_upstream_url:
            raise ConfigError(
                f"RERANKER_PROVIDER={self.reranker_provider} needs RERANKER_UPSTREAM_URL"
            )
        if self.embeddings_query_reserved_slots >= self.embeddings_upstream_concurrency:
            raise ConfigError(
                "EMBEDDINGS_QUERY_RESERVED_SLOTS must be lower than EMBEDDINGS_UPSTREAM_CONCURRENCY"
            )
        development = self.raggie_env.strip().lower() in DEVELOPMENT_ENVS
        if not self.require_auth and self.upstream_key_in_use:
            message = (
                "EMBEDDINGS_REQUIRE_AUTH=false while an upstream API key is configured: "
                "anything that can reach this service can spend that key"
            )
            if not development:
                raise ConfigError(
                    f"refusing to start with RAGGIE_ENV={self.raggie_env!r}: {message}; "
                    "set INTERNAL_API_SECRET and leave EMBEDDINGS_REQUIRE_AUTH unset"
                )
            logger.warning("%s (allowed only because RAGGIE_ENV=%s)", message, self.raggie_env)
        if self.require_auth:
            secret = self.internal_api_secret
            if not secret:
                raise ConfigError(
                    "EMBEDDINGS_REQUIRE_AUTH is on (default in cloud mode and with a "
                    "remote reranker) but INTERNAL_API_SECRET is empty"
                )
            # Same rule as the other services; the message never echoes the value.
            if not development:
                lowered = secret.lower()
                if "change-me" in lowered or "changeme" in lowered:
                    raise ConfigError(
                        f"refusing to start with RAGGIE_ENV={self.raggie_env!r}: "
                        "INTERNAL_API_SECRET is a placeholder (contains 'change-me')"
                    )
                if len(secret.encode()) < _SHARED_SECRET_MIN_BYTES:
                    raise ConfigError(
                        f"refusing to start with RAGGIE_ENV={self.raggie_env!r}: "
                        f"INTERNAL_API_SECRET is shorter than {_SHARED_SECRET_MIN_BYTES} bytes"
                    )


settings = Settings()
