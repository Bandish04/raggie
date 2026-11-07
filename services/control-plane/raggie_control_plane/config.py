# SPDX-License-Identifier: Apache-2.0

"""Control-plane configuration, loaded from the environment."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from raggie_control_plane.infra.secrets import resolve_secret

# Migrations ship next to the package (COPYed into the image at /app/migrations).
_DEFAULT_MIGRATIONS_DIR = str(Path(__file__).resolve().parent.parent / "migrations")


# Languages the product ships (kept in sync with users.locale's CHECK).
SUPPORTED_LOCALES = ("en", "tr")
# Default IANA timezone for new users and scheduled tasks (DEFAULT_TIMEZONE).
DEFAULT_TIMEZONE = "UTC"

EMBEDDINGS_FINGERPRINT_POLICIES = ("block_ingest", "refuse_boot", "auto_reindex")
_FINGERPRINT = re.compile(r"[0-9a-f]{8}")

_DEVELOPMENT_ENVS = frozenset({"development", "dev", "local"})
_TEST_ENVS = frozenset({"test", "testing"})


class Settings(BaseSettings):
    """Runtime configuration. Field names map to upper-cased env vars."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # development | test | production (case-insensitive; dev/local and testing
    # are aliases). Unset means production: strict secret validation, setup
    # token required, no API docs. "test" is the CI suite.
    raggie_env: str = "production"
    control_plane_port: int = 8000
    control_plane_log_level: str = "info"

    # Self-hosted update check. The running version + a remote release manifest URL
    # (JSON: {"version": "...", "notes": "...", "url": "..."}). The admin update
    # page compares them and shows the upgrade command — it NEVER controls the host
    # from the web (KVKK/on-prem safety). Empty manifest URL disables the check.
    # Install default language for new users (en | tr): DEFAULT_LOCALE, else the
    # web's NEXT_PUBLIC_DEFAULT_LOCALE, else English. See install_locale.
    default_locale: str = ""
    next_public_default_locale: str = ""
    # IANA timezone given to new users / scheduled tasks that don't pick one
    # (the web pre-fills the browser's zone). Existing rows keep theirs.
    default_timezone: str = DEFAULT_TIMEZONE

    app_version: str = "0.1.0"
    release_manifest_url: str = ""
    update_command: str = (
        "cd deploy/compose && docker compose --profile core pull && "
        "docker compose --profile core up -d"
    )

    # PostgreSQL.
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "raggie"
    postgres_user: str = "raggie"
    postgres_password: str = "raggie"
    # Full DSN override (e.g. pointing at PgBouncer); takes precedence when set.
    database_url: str | None = None
    db_pool_min_size: int = 2
    db_pool_max_size: int = 15

    # Auth / security. The dev defaults below are refused at boot outside
    # development/test (see validate_runtime_secrets); install.sh / k8s secrets
    # replace them.
    jwt_secret: str = "dev-insecure-jwt-secret-change-me-please"
    jwt_access_ttl_seconds: int = 28800  # 8 hours (full workday)
    jwt_refresh_ttl_seconds: int = 2_592_000  # 30 days
    # Refresh-token reuse detection revokes the session when a rotated-out token
    # reappears — except the immediate predecessor within this many seconds of
    # its rotation, which is a benign race between web replicas. 0 = strict.
    refresh_reuse_grace_seconds: int = 30
    widget_token_secret: str = "dev-insecure-widget-secret-change-me-please"
    invite_ttl_seconds: int = 604_800  # 7 days

    # One-time token required by POST /onboarding/bootstrap (first super admin).
    # Unset outside development: a random token is generated at first boot, its
    # sha256 stored, and the plaintext logged once.
    setup_token: str = ""

    # Integration credential encryption (Fernet key: url-safe base64, 32 bytes).
    # Required to connect any integration; generate with Fernet.generate_key().
    # Empty = integrations can be listed but not connected (no plaintext fallback).
    integration_enc_key: str = ""

    # SSO (OIDC) — behind the IdentityProvider seam; SAML would use the same seam.
    oidc_enabled: bool = False
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_authorize_url: str = ""
    oidc_token_url: str = ""
    oidc_userinfo_url: str = ""
    # Expected ID-token issuer (`iss`) and the IdP's JWKS endpoint. With a JWKS
    # URL the ID-token signature is verified; without one the token is trusted
    # only because it arrives directly from the token endpoint over TLS.
    oidc_issuer: str = ""
    oidc_jwks_url: str = ""
    oidc_redirect_url: str = "http://localhost:8000/api/v1/auth/sso/callback"
    oidc_default_role: str = "STAFF"
    sso_state_ttl_seconds: int = 600

    # SCIM 2.0 provisioning — bearer token presented by the IdP's SCIM client.
    scim_enabled: bool = False
    scim_bearer_token: str = ""
    # The one organization (UUID) the SCIM token provisions into. Every SCIM
    # read/write is confined to it; required when SCIM_ENABLED=true.
    scim_org_id: str = ""

    # Auth rate limiting (per client IP, sliding window).
    auth_rate_limit_max: int = 20
    auth_rate_limit_window_seconds: int = 60
    # Peers allowed to set X-Forwarded-For / X-Forwarded-Proto (the web tier,
    # ingress). Requests from any other peer are keyed on the socket address.
    trusted_proxy_cidrs: str = (
        "127.0.0.0/8,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,fc00::/7"
    )
    # Per-account progressive lockout after repeated failed logins: after
    # `threshold` failures inside `window`, the account is locked for `base`
    # seconds, doubling per further failure up to `max`.
    login_lockout_threshold: int = 5
    login_lockout_window_seconds: int = 900
    login_lockout_base_seconds: int = 30
    login_lockout_max_seconds: int = 900

    # Serve Swagger/ReDoc/OpenAPI outside development (off by default).
    expose_api_docs: bool = False
    # Optional bearer token required by GET /metrics (empty = unauthenticated,
    # keep the port private). Same semantics as the edge's METRICS_TOKEN.
    metrics_token: str = ""

    # Public base URL where the edge serves the widget loader (embed.js); used to
    # build the onboarding embed snippet.
    widget_embed_base_url: str = "http://localhost:8080"

    # GLOBAL kill switch for durable per-user memory (same env var the edge
    # reads). Effective only together with the per-workspace
    # workspaces.memory_enabled flag (default off). When off, importing memory is
    # refused; users can still view and erase what was already stored.
    memory_enabled: bool = True

    # Embeddings gateway (services/embeddings). Its GET /info names the active
    # embedding profile and the Qdrant collection uploads must target; the
    # control plane never derives a collection itself (embeddings_profile.py).
    embeddings_base_url: str = "http://embeddings:8002/v1"
    # Sent as "Authorization: Bearer ..." to the gateway when set (required by
    # the gateway in cloud mode). Same shared secret as the edge and workers.
    internal_api_secret: str = ""
    # What to do when the gateway's fingerprint differs from the one the live
    # documents are indexed with: block_ingest (uploads answer 409, /readyz stays
    # 200 "degraded") | refuse_boot (as block_ingest, /readyz 503) | auto_reindex
    # (re-embed everything, only when EMBEDDINGS_REEMBED_CONFIRM equals the NEW
    # fingerprint; otherwise as block_ingest).
    embeddings_fingerprint_policy: str = "block_ingest"
    embeddings_reembed_confirm: str = ""
    # How long a gateway /info answer is reused, and how often the profile is
    # re-checked against the indexed documents.
    embeddings_info_ttl_seconds: float = 60.0

    # Qdrant (read-only, for the admin vector-map visualization).
    qdrant_url: str = "http://qdrant:6333"
    qdrant_api_key: str = ""  # sent as the `api-key` header when set

    # Event bus (Redis Streams) + object store (MinIO) for document upload intake.
    redis_url: str = "redis://redis:6379"
    # REDIS_PASSWORD fills in when REDIS_URL carries none, and authenticates to
    # the data nodes in Sentinel mode. Sentinel (HA): when both ADDRS
    # (comma-separated host:port) and MASTER are set, REDIS_URL is ignored and
    # the client follows master failover. Half-configured = boot error.
    redis_password: str = ""
    redis_db: int = 0
    redis_sentinel_addrs: str = ""
    redis_sentinel_master: str = ""
    redis_sentinel_password: str = ""
    minio_endpoint: str = "minio:9000"
    minio_root_user: str = "raggie"
    minio_root_password: str = "raggie-minio"
    minio_bucket: str = "raggie-uploads"
    minio_use_ssl: bool = False

    # Large-file uploads: streamed in parts and assembled server-side via MinIO
    # compose, so neither the web tier nor the control-plane ever buffers a whole
    # file (only one part at a time). Parts (except the last) must be ≥5 MiB;
    # 16 MiB keeps part counts low. max_upload_bytes is a hard per-document ceiling
    # (default 10 GiB), configurable per deploy via MAX_UPLOAD_BYTES.
    upload_part_size: int = 16 * 1024 * 1024
    max_upload_bytes: int = 10 * 1024 * 1024 * 1024
    # The legacy multipart/form-data route still materializes one UploadFile in
    # the web stack. Keep it deliberately small; larger files use resumable parts.
    direct_upload_max_bytes: int = 32 * 1024 * 1024

    migrations_dir: str = _DEFAULT_MIGRATIONS_DIR
    run_migrations_on_boot: bool = True

    @model_validator(mode="after")
    def _resolve_file_secrets(self) -> Settings:
        # Prefer `<NAME>_FILE`-mounted secrets (sealed-secrets / Vault) over env.
        self.jwt_secret = resolve_secret("JWT_SECRET", self.jwt_secret)
        self.widget_token_secret = resolve_secret("WIDGET_TOKEN_SECRET", self.widget_token_secret)
        self.postgres_password = resolve_secret("POSTGRES_PASSWORD", self.postgres_password)
        self.scim_bearer_token = resolve_secret("SCIM_BEARER_TOKEN", self.scim_bearer_token)
        self.oidc_client_secret = resolve_secret("OIDC_CLIENT_SECRET", self.oidc_client_secret)
        self.integration_enc_key = resolve_secret("INTEGRATION_ENC_KEY", self.integration_enc_key)
        self.minio_root_password = resolve_secret("MINIO_ROOT_PASSWORD", self.minio_root_password)
        self.setup_token = resolve_secret("SETUP_TOKEN", self.setup_token)
        self.qdrant_api_key = resolve_secret("QDRANT_API_KEY", self.qdrant_api_key)
        self.metrics_token = resolve_secret("METRICS_TOKEN", self.metrics_token)
        self.internal_api_secret = resolve_secret("INTERNAL_API_SECRET", self.internal_api_secret)
        self.redis_password = resolve_secret("REDIS_PASSWORD", self.redis_password)
        self.redis_sentinel_password = resolve_secret(
            "REDIS_SENTINEL_PASSWORD", self.redis_sentinel_password
        )
        if self.database_url:
            self.database_url = resolve_secret("DATABASE_URL", self.database_url)
        return self

    @property
    def env(self) -> str:
        return self.raggie_env.strip().lower()

    @property
    def is_development(self) -> bool:
        return self.env in _DEVELOPMENT_ENVS

    @property
    def allows_insecure_defaults(self) -> bool:
        """Dev defaults (secrets, no setup token) are tolerated only here. Kept
        in sync with the workers' startup check."""
        return self.env in _DEVELOPMENT_ENVS or self.env in _TEST_ENVS

    @property
    def install_locale(self) -> str:
        for value in (self.default_locale, self.next_public_default_locale):
            if value.strip():
                return value.strip().lower()
        return "en"

    @property
    def redis_db_clamped(self) -> int:
        return min(max(self.redis_db, 0), 1024)  # same bounds as the edge

    @property
    def redis_sentinel_enabled(self) -> bool:
        return bool(self.redis_sentinel_addrs.strip()) and bool(self.redis_sentinel_master.strip())

    @property
    def dsn(self) -> str:
        if self.database_url:
            return self.database_url
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


class InsecureConfigurationError(RuntimeError):
    """Raised at boot when a secret is a known default or too weak."""


# Every in-repo default / placeholder a deployment might forget to replace.
_KNOWN_DEFAULT_SECRETS = frozenset(
    {
        "dev-insecure-jwt-secret-change-me-please",
        "dev-insecure-widget-secret-change-me-please",
        "change-me-to-a-random-32-byte-min-secret",
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
_MIN_SECRET_BYTES = 32
_MIN_PASSWORD_BYTES = 16


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True


def _secret_problem(value: str, min_bytes: int | None) -> str | None:
    if value in _KNOWN_DEFAULT_SECRETS:
        return "is a known default"
    if "change-me" in value.lower():
        return "is a placeholder (contains 'change-me')"
    if min_bytes is not None and len(value.encode()) < min_bytes:
        return f"is shorter than {min_bytes} bytes"
    return None


def _is_timezone(name: str) -> bool:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        ZoneInfo(name.strip())
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return False
    return bool(name.strip())


def validate_runtime_secrets(cfg: Settings) -> None:
    """Refuse to run outside development/test with default or weak secrets,
    and in every environment with a tenant-unsafe configuration.

    Every problem is collected so an operator fixes them in one pass."""
    if cfg.install_locale not in SUPPORTED_LOCALES:
        raise InsecureConfigurationError(
            "DEFAULT_LOCALE / NEXT_PUBLIC_DEFAULT_LOCALE must be one of "
            f"{', '.join(SUPPORTED_LOCALES)}."
        )
    if not _is_timezone(cfg.default_timezone):
        raise InsecureConfigurationError(
            "DEFAULT_TIMEZONE must be an IANA timezone name (e.g. UTC, Europe/Berlin)."
        )
    if bool(cfg.redis_sentinel_addrs.strip()) != bool(cfg.redis_sentinel_master.strip()):
        raise InsecureConfigurationError(
            "REDIS_SENTINEL_ADDRS and REDIS_SENTINEL_MASTER must be set together "
            "(or both left empty to use REDIS_URL)."
        )
    if cfg.scim_enabled and not _is_uuid(cfg.scim_org_id):
        # Not a secret but a tenant boundary: SCIM without a bound org would
        # read and provision across every organization.
        raise InsecureConfigurationError(
            "SCIM_ENABLED=true requires SCIM_ORG_ID set to the UUID of the organization "
            "the SCIM token provisions into."
        )
    if cfg.embeddings_fingerprint_policy not in EMBEDDINGS_FINGERPRINT_POLICIES:
        raise InsecureConfigurationError(
            "EMBEDDINGS_FINGERPRINT_POLICY must be one of "
            f"{', '.join(EMBEDDINGS_FINGERPRINT_POLICIES)}."
        )
    if cfg.embeddings_reembed_confirm and not _FINGERPRINT.fullmatch(
        cfg.embeddings_reembed_confirm
    ):
        raise InsecureConfigurationError(
            "EMBEDDINGS_REEMBED_CONFIRM must be empty or the 8-hex-digit fingerprint "
            "of the new embedding profile (shown in Admin → AI → Embeddings)."
        )
    if cfg.embeddings_info_ttl_seconds <= 0:
        raise InsecureConfigurationError("EMBEDDINGS_INFO_TTL_SECONDS must be positive.")
    if cfg.allows_insecure_defaults:
        return
    checks: list[tuple[str, str, int | None]] = [
        ("JWT_SECRET", cfg.jwt_secret, _MIN_SECRET_BYTES),
        ("WIDGET_TOKEN_SECRET", cfg.widget_token_secret, _MIN_SECRET_BYTES),
        ("MINIO_ROOT_PASSWORD", cfg.minio_root_password, _MIN_PASSWORD_BYTES),
    ]
    db_password = (
        urlsplit(cfg.database_url).password if cfg.database_url else (cfg.postgres_password)
    )
    if db_password is not None:
        checks.append(
            ("POSTGRES_PASSWORD (or the DATABASE_URL password)", db_password, _MIN_PASSWORD_BYTES)
        )
    # Optional secrets are validated only when configured / in use.
    if cfg.integration_enc_key:
        checks.append(("INTEGRATION_ENC_KEY", cfg.integration_enc_key, _MIN_SECRET_BYTES))
    if cfg.setup_token:
        checks.append(("SETUP_TOKEN", cfg.setup_token, _MIN_SECRET_BYTES))
    if cfg.metrics_token:
        checks.append(("METRICS_TOKEN", cfg.metrics_token, _MIN_SECRET_BYTES))
    if cfg.internal_api_secret:
        checks.append(("INTERNAL_API_SECRET", cfg.internal_api_secret, _MIN_SECRET_BYTES))
    if cfg.scim_enabled:
        checks.append(("SCIM_BEARER_TOKEN", cfg.scim_bearer_token, _MIN_SECRET_BYTES))
    if cfg.qdrant_api_key:  # optional; when set, the same rule as the edge and workers
        checks.append(("QDRANT_API_KEY", cfg.qdrant_api_key, _MIN_SECRET_BYTES))
    if not cfg.redis_sentinel_enabled and "change-me" in cfg.redis_url.lower():
        checks.append(("REDIS_URL", cfg.redis_url, None))

    problems = [
        f"{name} {problem}"
        for name, value, min_bytes in checks
        if (problem := _secret_problem(value, min_bytes)) is not None
    ]
    if problems:
        env = (
            f"RAGGIE_ENV={cfg.raggie_env!r}"
            if "raggie_env" in cfg.model_fields_set
            else "RAGGIE_ENV is unset (treated as production)"
        )
        raise InsecureConfigurationError(
            f"refusing to start with {env}: "
            + "; ".join(problems)
            + ". Generate strong values (e.g. `openssl rand -base64 48`) or set "
            "RAGGIE_ENV=development for a local, non-production install."
        )


def api_docs_enabled(cfg: Settings) -> bool:
    return cfg.is_development or cfg.expose_api_docs


settings = Settings()
