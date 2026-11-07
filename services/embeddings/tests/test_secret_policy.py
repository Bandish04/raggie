# SPDX-License-Identifier: Apache-2.0

import logging

import pytest
from conftest import make_settings

from raggie_embeddings.config import ConfigError

CLOUD = dict(
    embeddings_provider="openai_compatible",
    embeddings_upstream_base_url="https://api.example/v1",
)


def test_unset_raggie_env_means_production() -> None:
    assert make_settings().raggie_env == "production"


@pytest.mark.parametrize(
    "secret", ["short-secret", "please-change-me-" + "x" * 32, "CHANGEME" + "y" * 40]
)
def test_weak_secret_refused_in_production_when_auth_required(secret: str) -> None:
    with pytest.raises(ConfigError) as excinfo:
        make_settings(internal_api_secret=secret, **CLOUD).validate_for_boot()
    assert "INTERNAL_API_SECRET" in str(excinfo.value)
    assert secret not in str(excinfo.value)


def test_explicit_require_auth_in_local_mode_is_checked_too() -> None:
    with pytest.raises(ConfigError, match="INTERNAL_API_SECRET"):
        make_settings(embeddings_require_auth=True, internal_api_secret="tiny").validate_for_boot()


def test_a_set_secret_turns_auth_on_in_local_mode_and_is_checked() -> None:
    assert make_settings(internal_api_secret="k" * 32).require_auth is True
    assert make_settings().require_auth is False
    opted_out = make_settings(internal_api_secret="k" * 32, embeddings_require_auth=False)
    assert opted_out.require_auth is False
    with pytest.raises(ConfigError, match="INTERNAL_API_SECRET"):
        make_settings(internal_api_secret="short-secret").validate_for_boot()


@pytest.mark.parametrize("env", ["development", "Dev", "local", "test", "testing"])
def test_dev_envs_allow_weak_secrets(env: str) -> None:
    make_settings(raggie_env=env, internal_api_secret="dev", **CLOUD).validate_for_boot()


def test_strong_secret_passes() -> None:
    make_settings(internal_api_secret="k" * 32, **CLOUD).validate_for_boot()


def test_local_mode_without_auth_needs_no_secret() -> None:
    # Default local install: no auth, no secret, production env — boots.
    make_settings().validate_for_boot()


def test_empty_secret_still_refused_in_dev_when_auth_required() -> None:
    with pytest.raises(ConfigError, match="INTERNAL_API_SECRET"):
        make_settings(raggie_env="development", **CLOUD).validate_for_boot()


REMOTE_RERANK = dict(
    reranker_provider="cohere",
    reranker_upstream_url="https://api.cohere.example/v2/rerank",
    reranker_upstream_api_key="rk-paid",
)
CLOUD_WITH_KEY = dict(CLOUD, embeddings_upstream_api_key="sk-paid")


@pytest.mark.parametrize("provider", ["cohere", "voyage", "tei"])
def test_remote_reranker_requires_auth_by_default(provider: str) -> None:
    # Local dense + a remote reranker: the paid rerank key sits behind /v1/rerank.
    cfg = dict(REMOTE_RERANK, reranker_provider=provider)
    assert make_settings(**cfg).require_auth is True
    with pytest.raises(ConfigError, match="INTERNAL_API_SECRET"):
        make_settings(**cfg).validate_for_boot()
    make_settings(internal_api_secret="k" * 32, **cfg).validate_for_boot()


def test_disabled_remote_reranker_needs_no_auth() -> None:
    assert make_settings(reranker_enabled=False, **REMOTE_RERANK).require_auth is False


@pytest.mark.parametrize("upstream", [CLOUD_WITH_KEY, REMOTE_RERANK], ids=["dense", "rerank"])
def test_auth_off_with_an_upstream_key_is_refused_in_production(upstream: dict) -> None:
    with pytest.raises(ConfigError, match="EMBEDDINGS_REQUIRE_AUTH=false"):
        make_settings(embeddings_require_auth=False, **upstream).validate_for_boot()


def test_auth_off_with_an_upstream_key_only_warns_in_development(caplog) -> None:
    cfg = make_settings(raggie_env="development", embeddings_require_auth=False, **REMOTE_RERANK)
    with caplog.at_level(logging.WARNING, logger="raggie.embeddings.config"):
        cfg.validate_for_boot()
    assert any("EMBEDDINGS_REQUIRE_AUTH=false" in r.getMessage() for r in caplog.records)
    assert not any("rk-paid" in r.getMessage() for r in caplog.records)


def test_auth_off_without_an_upstream_key_is_allowed() -> None:
    make_settings(embeddings_require_auth=False).validate_for_boot()
    keyless_tei = dict(REMOTE_RERANK, reranker_provider="tei", reranker_upstream_api_key="")
    make_settings(embeddings_require_auth=False, **keyless_tei).validate_for_boot()
