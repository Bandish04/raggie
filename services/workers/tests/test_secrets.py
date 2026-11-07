# SPDX-License-Identifier: Apache-2.0

"""Startup hardening: a non-development worker must refuse to boot with a
shipped/placeholder secret, and must be able to use authenticated Redis/Qdrant."""

import pytest

import raggie_workers.main as main_module
from raggie_workers.config import InsecureConfigError, Settings, validate_secrets

STRONG_SECRET = "x" * 40
STRONG_PASSWORD = "Pg-Strong-Password-1"


def _settings(monkeypatch, **env: str) -> Settings:
    for key in (
        "RAGGIE_ENV",
        "INTERNAL_API_SECRET",
        "POSTGRES_PASSWORD",
        "DATABASE_URL",
        "MINIO_ROOT_PASSWORD",
        "QDRANT_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None)


def _hardened(monkeypatch, **overrides: str) -> Settings:
    env = {
        "RAGGIE_ENV": "production",
        "INTERNAL_API_SECRET": STRONG_SECRET,
        "POSTGRES_PASSWORD": STRONG_PASSWORD,
        "MINIO_ROOT_PASSWORD": "Minio-Strong-Pass-9",
    }
    env.update(overrides)
    return _settings(monkeypatch, **env)


def test_unset_raggie_env_means_production(monkeypatch) -> None:
    settings = _settings(monkeypatch)
    assert settings.raggie_env == "production"
    with pytest.raises(InsecureConfigError):
        validate_secrets(settings)  # shipped defaults: POSTGRES/MINIO passwords


@pytest.mark.parametrize("env", ["development", "Development", "dev", "test", "testing", "local"])
def test_development_envs_allow_defaults(monkeypatch, env: str) -> None:
    validate_secrets(_settings(monkeypatch, RAGGIE_ENV=env))


def test_hardened_production_config_passes(monkeypatch) -> None:
    validate_secrets(_hardened(monkeypatch))


def test_empty_internal_secret_is_allowed(monkeypatch) -> None:
    # Empty keeps the scheduler / internal endpoint dormant; that is safe.
    validate_secrets(_hardened(monkeypatch, INTERNAL_API_SECRET=""))


@pytest.mark.parametrize(
    ("env", "value"),
    [
        ("INTERNAL_API_SECRET", "short-secret"),
        ("INTERNAL_API_SECRET", "please-change-me-" + "x" * 32),
        ("POSTGRES_PASSWORD", "raggie"),
        ("POSTGRES_PASSWORD", "tiny-pw"),
        ("POSTGRES_PASSWORD", "CHANGE-ME-postgres-password"),
        ("MINIO_ROOT_PASSWORD", "raggie-minio"),
        ("MINIO_ROOT_PASSWORD", "change-me-minio"),
        ("MINIO_ROOT_PASSWORD", "minioadmin"),
        ("MINIO_ROOT_PASSWORD", "tooshort"),
    ],
)
def test_weak_secret_refuses_to_start(monkeypatch, env: str, value: str) -> None:
    with pytest.raises(InsecureConfigError) as excinfo:
        validate_secrets(_hardened(monkeypatch, **{env: value}))
    message = str(excinfo.value)
    assert env in message
    assert value not in message  # never echo the secret itself


def test_database_url_password_is_checked(monkeypatch) -> None:
    weak = "postgresql://raggie:raggie@db:5432/raggie"
    with pytest.raises(InsecureConfigError, match="DATABASE_URL"):
        validate_secrets(_hardened(monkeypatch, DATABASE_URL=weak))
    strong = f"postgresql://raggie:{STRONG_PASSWORD}@db:5432/raggie"
    # DATABASE_URL wins over POSTGRES_PASSWORD, so a weak unused one is fine.
    validate_secrets(_hardened(monkeypatch, DATABASE_URL=strong, POSTGRES_PASSWORD="raggie"))


def test_all_problems_reported_at_once(monkeypatch) -> None:
    settings = _hardened(
        monkeypatch, POSTGRES_PASSWORD="raggie", MINIO_ROOT_PASSWORD="raggie-minio"
    )
    with pytest.raises(InsecureConfigError) as excinfo:
        validate_secrets(settings)
    assert "POSTGRES_PASSWORD" in str(excinfo.value)
    assert "MINIO_ROOT_PASSWORD" in str(excinfo.value)


def test_main_refuses_to_boot_with_default_secrets(monkeypatch) -> None:
    monkeypatch.setattr(main_module, "settings", _settings(monkeypatch, RAGGIE_ENV="production"))
    started: list[int] = []
    monkeypatch.setattr(main_module, "start_health_server", started.append)
    with pytest.raises(InsecureConfigError):
        main_module.main()
    assert started == []  # failed before serving anything


# ───────────────────────────── Qdrant / Redis auth ─────────────────────────


def test_qdrant_client_receives_api_key(monkeypatch) -> None:
    seen: dict = {}

    class _Recorder:
        def __init__(self, **kwargs) -> None:
            seen.update(kwargs)

    monkeypatch.setattr(main_module, "AsyncQdrantClient", _Recorder)
    main_module.qdrant_client(_settings(monkeypatch, QDRANT_API_KEY="qdrant-key-123"))
    assert seen == {"url": "http://qdrant:6333", "api_key": "qdrant-key-123"}


def test_qdrant_client_without_key_sends_none(monkeypatch) -> None:
    seen: dict = {}

    class _Recorder:
        def __init__(self, **kwargs) -> None:
            seen.update(kwargs)

    monkeypatch.setattr(main_module, "AsyncQdrantClient", _Recorder)
    main_module.qdrant_client(_settings(monkeypatch))
    assert seen["api_key"] is None


def test_redis_url_with_password_is_honoured(monkeypatch) -> None:
    settings = _settings(monkeypatch, REDIS_URL="redis://:s3cr%40t-pass@redis:6380/2")
    client = main_module.redis_client(settings)
    kwargs = client.connection_pool.connection_kwargs
    assert kwargs["password"] == "s3cr@t-pass"
    assert kwargs["host"] == "redis"
    assert kwargs["port"] == 6380
    assert kwargs["db"] == 2
    assert kwargs["decode_responses"] is True


@pytest.mark.parametrize("weak", ["change-me", "short-but-random-Qd7"])
def test_weak_qdrant_api_key_is_refused(monkeypatch, weak: str) -> None:
    # Same rule as the control plane and the edge: a set key must be strong.
    with pytest.raises(InsecureConfigError, match="QDRANT_API_KEY"):
        validate_secrets(_hardened(monkeypatch, QDRANT_API_KEY=weak))


def test_empty_qdrant_api_key_is_allowed(monkeypatch) -> None:
    validate_secrets(_hardened(monkeypatch, QDRANT_API_KEY=""))
