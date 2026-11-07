# SPDX-License-Identifier: Apache-2.0

"""Boot-time secret validation and environment-gated HTTP hardening."""

import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport

from raggie_control_plane.config import (
    InsecureConfigurationError,
    Settings,
    api_docs_enabled,
    validate_runtime_secrets,
)
from raggie_control_plane.config import settings as live_settings
from raggie_control_plane.main import app

STRONG_JWT = "j" * 48
STRONG_WIDGET = "w" * 48
STRONG_DSN = "postgresql://raggie:Str0ng-Postgres-Passw0rd@db:5432/raggie"


def _prod(**overrides) -> Settings:
    base: dict = {
        "raggie_env": "production",
        "jwt_secret": STRONG_JWT,
        "widget_token_secret": STRONG_WIDGET,
        "minio_root_password": "m1n10-Str0ng-Passw0rd",
        "database_url": STRONG_DSN,
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)


def test_unset_raggie_env_means_production(monkeypatch) -> None:
    monkeypatch.delenv("RAGGIE_ENV", raising=False)
    assert Settings(_env_file=None).raggie_env == "production"


def test_strong_production_config_passes() -> None:
    validate_runtime_secrets(_prod())


@pytest.mark.parametrize(
    ("field", "value", "env_name"),
    [
        ("jwt_secret", "dev-insecure-jwt-secret-change-me-please", "JWT_SECRET"),
        ("jwt_secret", "short-but-random-Zq81", "JWT_SECRET"),
        ("widget_token_secret", "x" * 40 + "change-me", "WIDGET_TOKEN_SECRET"),
        (
            "widget_token_secret",
            "dev-insecure-widget-secret-change-me-please",
            "WIDGET_TOKEN_SECRET",
        ),
        ("minio_root_password", "raggie-minio", "MINIO_ROOT_PASSWORD"),
        ("minio_root_password", "minioadmin", "MINIO_ROOT_PASSWORD"),
        ("minio_root_password", "change-me-minio", "MINIO_ROOT_PASSWORD"),
        ("minio_root_password", "fifteen-chars-x", "MINIO_ROOT_PASSWORD"),
        ("database_url", "postgresql://raggie:raggie@db:5432/raggie", "POSTGRES_PASSWORD"),
        (
            "integration_enc_key",
            "change-me-to-a-fernet-key-please-0123456789",
            "INTEGRATION_ENC_KEY",
        ),
        ("setup_token", "too-short", "SETUP_TOKEN"),
        ("qdrant_api_key", "change-me", "QDRANT_API_KEY"),
        # Same rule as the edge and workers: a set key must be >= 32 bytes.
        ("qdrant_api_key", "short-but-random-Qd7", "QDRANT_API_KEY"),
    ],
)
def test_weak_secret_refuses_production(field, value, env_name) -> None:
    with pytest.raises(InsecureConfigurationError) as exc:
        validate_runtime_secrets(_prod(**{field: value}))
    assert env_name in str(exc.value)


def test_postgres_password_checked_when_no_dsn() -> None:
    cfg = _prod(database_url=None, postgres_password="raggie")
    with pytest.raises(InsecureConfigurationError, match="POSTGRES_PASSWORD"):
        validate_runtime_secrets(cfg)


def test_scim_token_checked_only_when_enabled() -> None:
    validate_runtime_secrets(_prod(scim_enabled=False, scim_bearer_token="weak"))
    with pytest.raises(InsecureConfigurationError, match="SCIM_BEARER_TOKEN"):
        validate_runtime_secrets(
            _prod(
                scim_enabled=True,
                scim_bearer_token="weak",
                scim_org_id="6f1c0e0a-1111-4222-8333-444455556666",
            )
        )


def test_error_names_variables_never_values() -> None:
    weak = "weak-jwt-value-xyz"
    with pytest.raises(InsecureConfigurationError) as exc:
        validate_runtime_secrets(_prod(jwt_secret=weak))
    assert "JWT_SECRET" in str(exc.value) and weak not in str(exc.value)


def test_unknown_env_is_strict() -> None:
    with pytest.raises(InsecureConfigurationError):
        validate_runtime_secrets(Settings(_env_file=None, raggie_env="staging", jwt_secret="short"))


def test_all_problems_reported_at_once() -> None:
    cfg = _prod(
        jwt_secret="dev-insecure-jwt-secret-change-me-please",
        minio_root_password="raggie-minio",
    )
    with pytest.raises(InsecureConfigurationError) as exc:
        validate_runtime_secrets(cfg)
    assert "JWT_SECRET" in str(exc.value) and "MINIO_ROOT_PASSWORD" in str(exc.value)


@pytest.mark.parametrize("env", ["development", "Dev", "local", "test", "TESTING"])
def test_dev_and_test_envs_keep_defaults(monkeypatch, env) -> None:
    for name in ("JWT_SECRET", "WIDGET_TOKEN_SECRET", "MINIO_ROOT_PASSWORD", "DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)
    validate_runtime_secrets(Settings(_env_file=None, raggie_env=env))


def test_app_refuses_to_boot_with_default_secrets(monkeypatch) -> None:
    monkeypatch.setattr(live_settings, "raggie_env", "production")
    monkeypatch.setattr(live_settings, "jwt_secret", "dev-insecure-jwt-secret-change-me-please")
    with pytest.raises(InsecureConfigurationError), TestClient(app):
        pass


def test_error_says_when_raggie_env_is_unset(monkeypatch) -> None:
    monkeypatch.delenv("RAGGIE_ENV", raising=False)
    with pytest.raises(InsecureConfigurationError) as unset:
        validate_runtime_secrets(Settings(_env_file=None, jwt_secret="short"))
    assert "RAGGIE_ENV is unset (treated as production)" in str(unset.value)
    with pytest.raises(InsecureConfigurationError) as explicit:
        validate_runtime_secrets(_prod(jwt_secret="short"))
    assert "RAGGIE_ENV='production'" in str(explicit.value)


def test_server_boot_prints_the_reason_without_a_traceback(tmp_path) -> None:
    # What `uvicorn raggie_control_plane.main:app` shows an operator who left
    # RAGGIE_ENV unset: the reason on stderr and a non-zero exit, no traceback.
    env = {
        k: v
        for k, v in os.environ.items()
        if k != "RAGGIE_ENV" and not k.endswith(("_SECRET", "_PASSWORD", "_URL"))
    }
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    proc = subprocess.run(
        [sys.executable, "-c", "import raggie_control_plane.main"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 1
    assert proc.stderr.startswith("control-plane: refusing to start with RAGGIE_ENV is unset")
    assert "Traceback" not in proc.stderr


# ── Security headers / API docs ──────────────────────────────────────────────
async def _get(path: str, headers: dict | None = None) -> httpx.Response:
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        return await c.get(path, headers=headers or {})


async def test_security_headers_in_non_development_env() -> None:
    assert live_settings.raggie_env == "test"
    r = await _get("/healthz")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Referrer-Policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
    assert "Strict-Transport-Security" not in r.headers  # plain http


async def test_hsts_only_behind_https_from_trusted_proxy() -> None:
    # ASGITransport's peer is 127.0.0.1 (loopback = trusted proxy by default).
    r = await _get("/healthz", headers={"X-Forwarded-Proto": "https"})
    assert r.headers["Strict-Transport-Security"].startswith("max-age=")


async def test_api_docs_hidden_outside_development() -> None:
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert (await _get(path)).status_code == 404


def test_api_docs_toggle() -> None:
    assert api_docs_enabled(Settings(_env_file=None, raggie_env="development"))
    assert not api_docs_enabled(Settings(_env_file=None, raggie_env="production"))
    assert api_docs_enabled(Settings(_env_file=None, raggie_env="production", expose_api_docs=True))


@pytest.mark.parametrize("env", ["development", "production"])
def test_scim_enabled_requires_org_binding_in_every_env(env) -> None:
    base = _prod(raggie_env=env, scim_enabled=True, scim_bearer_token="s" * 40)
    with pytest.raises(InsecureConfigurationError, match="SCIM_ORG_ID"):
        validate_runtime_secrets(base.model_copy(update={"scim_org_id": ""}))
    with pytest.raises(InsecureConfigurationError, match="SCIM_ORG_ID"):
        validate_runtime_secrets(base.model_copy(update={"scim_org_id": "not-a-uuid"}))
    validate_runtime_secrets(
        base.model_copy(update={"scim_org_id": "6f1c0e0a-1111-4222-8333-444455556666"})
    )


async def test_metrics_public_without_token(monkeypatch) -> None:
    monkeypatch.setattr(live_settings, "metrics_token", "")
    assert (await _get("/metrics")).status_code == 200


async def test_metrics_require_bearer_when_token_set(monkeypatch) -> None:
    token = "metrics-scrape-token-0123456789abcdef"
    monkeypatch.setattr(live_settings, "metrics_token", token)
    assert (await _get("/metrics")).status_code == 401
    assert (await _get("/metrics", {"Authorization": "Bearer nope"})).status_code == 401
    assert (await _get("/metrics", {"Authorization": "Bearer şifre".encode()})).status_code == 401
    assert (await _get("/metrics", {"Authorization": f"Bearer {token}"})).status_code == 200


def test_metrics_token_validated_when_set() -> None:
    with pytest.raises(InsecureConfigurationError, match="METRICS_TOKEN"):
        validate_runtime_secrets(_prod(metrics_token="change-me"))
    validate_runtime_secrets(_prod(metrics_token="m" * 40))


def test_embeddings_defaults() -> None:
    cfg = Settings(_env_file=None)
    assert cfg.embeddings_fingerprint_policy == "block_ingest"
    assert cfg.embeddings_reembed_confirm == ""
    assert cfg.embeddings_info_ttl_seconds == 60


@pytest.mark.parametrize("env", ["development", "production"])
def test_embeddings_policy_and_confirmation_are_validated(env) -> None:
    base = _prod(raggie_env=env)
    with pytest.raises(InsecureConfigurationError, match="EMBEDDINGS_FINGERPRINT_POLICY"):
        validate_runtime_secrets(base.model_copy(update={"embeddings_fingerprint_policy": "yolo"}))
    with pytest.raises(InsecureConfigurationError, match="EMBEDDINGS_REEMBED_CONFIRM"):
        validate_runtime_secrets(base.model_copy(update={"embeddings_reembed_confirm": "yes"}))
    with pytest.raises(InsecureConfigurationError, match="EMBEDDINGS_INFO_TTL_SECONDS"):
        validate_runtime_secrets(base.model_copy(update={"embeddings_info_ttl_seconds": 0}))
    validate_runtime_secrets(
        base.model_copy(
            update={
                "embeddings_fingerprint_policy": "auto_reindex",
                "embeddings_reembed_confirm": "5e1f00d2",
            }
        )
    )


def test_internal_api_secret_validated_when_set() -> None:
    with pytest.raises(InsecureConfigurationError, match="INTERNAL_API_SECRET"):
        validate_runtime_secrets(_prod(internal_api_secret="short"))
    validate_runtime_secrets(_prod(internal_api_secret="i" * 40))


def test_empty_qdrant_api_key_is_allowed() -> None:
    # Qdrant auth is optional (as in the edge and workers); only a set key is checked.
    validate_runtime_secrets(_prod(qdrant_api_key=""))
