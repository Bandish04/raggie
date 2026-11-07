# SPDX-License-Identifier: Apache-2.0

"""Worker configuration, loaded from the environment."""

from __future__ import annotations

from urllib.parse import unquote, urlsplit

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SUPPORTED_LOCALES = ("en", "tr")


class Settings(BaseSettings):
    """Field names map to upper-cased env vars (e.g. worker_role -> WORKER_ROLE)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Unset means production: the secret checks in validate_secrets() apply
    # unless the operator explicitly opts into a development/test environment.
    raggie_env: str = "production"
    # Fallback language (en | tr) for user-facing text when the owner has none:
    # DEFAULT_LOCALE, else the web's NEXT_PUBLIC_DEFAULT_LOCALE, else English
    # (same resolution as the control-plane).
    default_locale: str = ""
    next_public_default_locale: str = ""
    # IANA timezone for a scheduled task whose stored zone is missing/invalid
    # (DEFAULT_TIMEZONE, same knob and default as the control-plane).
    default_timezone: str = "UTC"
    worker_role: str = "ingestion"  # ingestion | eval | scheduler
    worker_log_level: str = "info"
    worker_health_port: int = 9100

    # Scheduler worker (runs due scheduled_tasks). It claims tasks by next_run_at
    # and calls the edge's internal run-task endpoint to execute each prompt.
    # INTERNAL_API_SECRET is the shared secret for that server-to-server call; if
    # empty the role idles (the edge endpoint is dormant without it too).
    edge_url: str = "http://edge:8080"
    internal_api_secret: str = ""
    scheduler_poll_seconds: int = 30
    # Total seconds one run-task call to the edge may take, clamped to
    # [10, 1800]. A deep-research run chains searches and a full LLM answer; on
    # a CPU-only local model it must exceed the edge's first-byte wait
    # (LLMAAS_RESPONSE_HEADER_TIMEOUT_SECONDS) plus generation.
    scheduler_task_timeout_seconds: float = 150.0

    # Auto-retry sweep (folded into the scheduler worker). Every
    # retry_sweep_seconds it re-enqueues FAILED documents whose backoff has
    # elapsed, up to max_retries attempts (the per-doc cap lives in the
    # documents.max_retries column, default 3). Backoff is exponential by
    # retry_count (1, 2, 4, ... minutes) capped at retry_backoff_cap_seconds so a
    # high retry_count can't push the next attempt arbitrarily far out.
    retry_sweep_seconds: int = 60
    retry_backoff_cap_seconds: int = 3600
    # Max FAILED docs re-armed per sweep tick (bounds each tick's work + publishes).
    retry_sweep_batch: int = 50
    # Stale-PENDING sweep (same loop): a document.uploaded event lost in a Redis
    # failover (replication is async) would leave a doc PENDING forever. Live
    # PENDING/PROCESSING docs whose updated_at has not moved for this long are
    # re-published (ingestion is idempotent). Ingestion heartbeats updated_at
    # every ingest_heartbeat_seconds while it works, so active docs never look
    # stale; the heartbeat must be well below the threshold.
    stale_pending_seconds: int = Field(default=900, ge=60)
    stale_pending_batch: int = Field(default=50, ge=1)
    ingest_heartbeat_seconds: float = Field(default=60.0, gt=0)

    # Chat LLM (OpenAI-compatible /v1) used by the eval worker's judge.
    llmaas_base_url: str = "https://api.llmaas.example/v1"
    llmaas_api_key: str = "change-me"
    llmaas_chat_model: str = "gpt-oss-120b"

    # Auto-evaluator. Score < threshold flags the conversation. Sampling
    # kicks in only above the QPS threshold; the eval pool is bounded so it
    # never starves the chat/retrieval hot path.
    eval_faithfulness_threshold: float = Field(
        default=0.7,
        validation_alias=AliasChoices(
            "EVAL_FAITHFULNESS_THRESHOLD",
            "EVAL_SCORE_THRESHOLD",
        ),
    )
    eval_citation_validity_threshold: float = 1.0
    eval_citation_coverage_threshold: float = 0.6
    eval_sample_rate: float = 1.0
    eval_qps_threshold: float = 20.0
    eval_max_concurrency: int = 4
    # Total seconds one judge call may take, clamped to [5, 900]. The judge is
    # non-streaming, so this covers prompt processing plus the whole reply; a
    # CPU-only local model (bundled Ollama) needs minutes, not the default 30.
    eval_llm_timeout_seconds: float = 30.0
    # Deliveries of one chat.completed event before a failing judge (5xx,
    # connection refused) gives up: the event is then acked and recorded
    # without a faithfulness score. Below the cap it is redelivered.
    eval_max_deliveries: int = Field(default=5, ge=1)
    eval_dedup_ttl_seconds: int = 86_400

    @field_validator("eval_llm_timeout_seconds")
    @classmethod
    def _clamp_eval_llm_timeout(cls, value: float) -> float:
        return min(max(value, 5.0), 900.0)

    @field_validator("scheduler_task_timeout_seconds")
    @classmethod
    def _clamp_scheduler_task_timeout(cls, value: float) -> float:
        return min(max(value, 10.0), 1800.0)

    # Embeddings come from our own local service (the chat provider has none).
    # Dense dim MUST match the embeddings model (intfloat/multilingual-e5-large →
    # 1024) and the control-plane default.
    embeddings_base_url: str = "http://embeddings:8002/v1"
    # Gateway calls carry passages for a whole document batch; the gateway itself
    # retries its upstream and answers 429 + Retry-After when it gives up.
    embed_timeout_seconds: float = Field(default=180.0, gt=0)
    embed_max_retries: int = Field(default=6, ge=0)
    embedding_dim: int = 1024
    # Chunks per embeddings-gateway request (the gateway sub-batches further
    # for its upstream).
    embed_batch_size: int = Field(default=64, ge=1)
    # Hybrid: also compute BM25 sparse vectors per chunk (via the embeddings
    # service /v1/sparse) and index them alongside dense. Off → dense-only.
    sparse_enabled: bool = True

    # Bounded document parsing. OOXML central directories are inspected before
    # decompression, and every parse runs in a disposable child process that is
    # killed when it exceeds the wall-clock budget. The short PARSE_*/OCR_* names
    # are accepted as aliases.
    parser_timeout_seconds: float = Field(
        default=120.0,
        gt=0,
        le=3600,
        validation_alias=AliasChoices("PARSER_TIMEOUT_SECONDS", "PARSE_TIMEOUT_SECONDS"),
    )
    parser_max_archive_uncompressed_bytes: int = Field(
        default=256 * 1024 * 1024,
        gt=0,
        validation_alias=AliasChoices(
            "PARSER_MAX_ARCHIVE_UNCOMPRESSED_BYTES", "PARSE_MAX_UNCOMPRESSED_BYTES"
        ),
    )
    parser_max_extracted_chars: int = Field(default=10_000_000, gt=0)
    parser_max_xlsx_cells: int = Field(default=1_000_000, gt=0)
    parser_max_pptx_shapes: int = Field(default=50_000, gt=0)
    # PDFs with more pages are rejected before any page is parsed.
    parser_max_pdf_pages: int = Field(
        default=1000,
        gt=0,
        validation_alias=AliasChoices("PARSER_MAX_PDF_PAGES", "PARSE_MAX_PAGES"),
    )
    # Pixel budget per OCR bitmap: PDF pages render at a scale that fits it (a
    # forged MediaBox cannot allocate gigapixels); larger images are downscaled,
    # and ones above 4x the budget are rejected.
    parser_ocr_max_pixels: int = Field(
        default=25_000_000,
        gt=0,
        validation_alias=AliasChoices("PARSER_OCR_MAX_PIXELS", "OCR_MAX_PIXELS"),
    )

    # Vector DB. QDRANT_API_KEY is sent when set (Qdrant service.api_key);
    # empty keeps the unauthenticated single-node default.
    qdrant_url: str = "http://qdrant:6333"
    qdrant_api_key: str = ""
    # Topology for collections this worker creates (HA Qdrant cluster). The
    # single-node default is 1/1/1; existing collections are never altered.
    qdrant_replication_factor: int = Field(default=1, ge=1)
    qdrant_shard_number: int = Field(default=1, ge=1)
    qdrant_write_consistency_factor: int = Field(default=1, ge=1)

    # Event bus (Redis Streams). A password goes in the URL
    # (redis://:<url-encoded-password>@redis:6379/0, rediss:// for TLS) or in
    # REDIS_PASSWORD, which fills in when the URL carries none and authenticates
    # to the data nodes in Sentinel mode. Sentinel (HA): when both ADDRS
    # (comma-separated host:port) and MASTER are set, REDIS_URL is ignored and
    # the client follows master failover. Half-configured = boot error.
    redis_url: str = "redis://redis:6379"
    redis_password: str = ""
    redis_db: int = 0
    redis_sentinel_addrs: str = ""
    redis_sentinel_master: str = ""
    redis_sentinel_password: str = ""

    # PostgreSQL (documents status writes).
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "raggie"
    postgres_user: str = "raggie"
    postgres_password: str = "raggie"
    database_url: str | None = None

    # MinIO (raw uploaded files).
    minio_endpoint: str = "minio:9000"
    minio_root_user: str = "raggie"
    minio_root_password: str = "raggie-minio"
    minio_bucket: str = "raggie-uploads"
    minio_use_ssl: bool = False

    @model_validator(mode="after")
    def _heartbeat_below_staleness(self) -> Settings:
        if self.ingest_heartbeat_seconds >= self.stale_pending_seconds:
            raise ValueError(
                "INGEST_HEARTBEAT_SECONDS must be lower than STALE_PENDING_SECONDS "
                "(otherwise documents still being ingested look stale)"
            )
        return self

    @property
    def dsn(self) -> str:
        if self.database_url:
            return self.database_url
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def install_locale(self) -> str:
        for value in (self.default_locale, self.next_public_default_locale):
            if value.strip().lower() in SUPPORTED_LOCALES:
                return value.strip().lower()
        return "en"

    @property
    def redis_db_clamped(self) -> int:
        return min(max(self.redis_db, 0), 1024)  # same bounds as the edge

    @property
    def redis_sentinel_enabled(self) -> bool:
        return bool(self.redis_sentinel_addrs.strip()) and bool(self.redis_sentinel_master.strip())

    def parser_limits(self):
        # Local import avoids making config import parser dependencies at startup.
        from raggie_workers.ingestion.parsing import ParserLimits

        return ParserLimits(
            max_archive_uncompressed_bytes=self.parser_max_archive_uncompressed_bytes,
            max_extracted_chars=self.parser_max_extracted_chars,
            max_xlsx_cells=self.parser_max_xlsx_cells,
            max_pptx_shapes=self.parser_max_pptx_shapes,
            max_pdf_pages=self.parser_max_pdf_pages,
            ocr_max_pixels=self.parser_ocr_max_pixels,
        )


settings = Settings()


# ───────────────────────────── Startup secret checks ─────────────────────────
# Outside development/test the worker refuses to boot with a shipped default or
# placeholder secret: a public repo makes every default a known credential.

DEVELOPMENT_ENVS = frozenset({"development", "dev", "local", "test", "testing"})
_SHARED_SECRET_MIN_BYTES = 32
_PASSWORD_MIN_BYTES = 16
_KNOWN_DEFAULT_PASSWORDS = frozenset(
    {
        "raggie",
        "raggie-minio",
        "change-me-minio",
        "minioadmin",
        "postgres",
        "password",
        "admin",
        "secret",
    }
)


class InsecureConfigError(RuntimeError):
    """Raised at startup when a production worker is configured with weak secrets."""


def _secret_problem(value: str, min_bytes: int) -> str | None:
    if value.lower() in _KNOWN_DEFAULT_PASSWORDS:
        return "is a known default"
    if "change-me" in value.lower() or "changeme" in value.lower():
        return "is a placeholder (contains 'change-me')"
    if len(value.encode()) < min_bytes:
        return f"is shorter than {min_bytes} bytes"
    return None


def validate_secrets(cfg: Settings) -> None:
    """Refuse weak secrets unless RAGGIE_ENV is a development/test environment.

    The error names the offending variables, never their values. A
    half-configured Redis Sentinel is refused in every environment.
    """
    if bool(cfg.redis_sentinel_addrs.strip()) != bool(cfg.redis_sentinel_master.strip()):
        raise InsecureConfigError(
            "REDIS_SENTINEL_ADDRS and REDIS_SENTINEL_MASTER must be set together "
            "(or both left empty to use REDIS_URL)."
        )
    if cfg.raggie_env.strip().lower() in DEVELOPMENT_ENVS:
        return
    checks: list[tuple[str, str, int]] = []
    # Empty INTERNAL_API_SECRET is allowed: the scheduler and the edge's
    # internal endpoint both stay dormant without it.
    if cfg.internal_api_secret:
        checks.append(("INTERNAL_API_SECRET", cfg.internal_api_secret, _SHARED_SECRET_MIN_BYTES))
    if cfg.database_url:
        # A password-less DSN (peer/cert auth) has nothing to check here.
        password = urlsplit(cfg.database_url).password
        if password is not None:
            checks.append(("DATABASE_URL", unquote(password), _PASSWORD_MIN_BYTES))
    else:
        checks.append(("POSTGRES_PASSWORD", cfg.postgres_password, _PASSWORD_MIN_BYTES))
    checks.append(("MINIO_ROOT_PASSWORD", cfg.minio_root_password, _PASSWORD_MIN_BYTES))
    # Qdrant auth is optional (as in the control plane and the edge); a set key
    # must be a strong shared secret.
    if cfg.qdrant_api_key:
        checks.append(("QDRANT_API_KEY", cfg.qdrant_api_key, _SHARED_SECRET_MIN_BYTES))

    problems = [
        f"{name} {problem}"
        for name, value, min_bytes in checks
        if (problem := _secret_problem(value, min_bytes)) is not None
    ]
    if problems:
        raise InsecureConfigError(
            f"refusing to start with RAGGIE_ENV={cfg.raggie_env!r}: "
            + "; ".join(problems)
            + ". Set strong values (or RAGGIE_ENV=development for local use)."
        )
