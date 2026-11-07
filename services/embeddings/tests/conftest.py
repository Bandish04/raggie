# SPDX-License-Identifier: Apache-2.0

import pytest

from raggie_embeddings.config import Settings

_ENV = [
    "EMBEDDINGS_PROVIDER",
    "EMBEDDINGS_MODEL",
    "EMBEDDING_DIM",
    "EMBEDDINGS_QUERY_PREFIX",
    "EMBEDDINGS_PASSAGE_PREFIX",
    "EMBEDDINGS_UPSTREAM_BASE_URL",
    "EMBEDDINGS_UPSTREAM_API_KEY",
    "EMBEDDINGS_REQUEST_EXTRA_JSON",
    "EMBEDDINGS_QUERY_EXTRA_JSON",
    "EMBEDDINGS_PASSAGE_EXTRA_JSON",
    "EMBEDDINGS_REQUIRE_AUTH",
    "EMBEDDINGS_CACHE_REDIS_URL",
    "REDIS_URL",
    "REDIS_PASSWORD",
    "REDIS_DB",
    "REDIS_SENTINEL_ADDRS",
    "REDIS_SENTINEL_MASTER",
    "REDIS_SENTINEL_PASSWORD",
    "INTERNAL_API_SECRET",
    "RAGGIE_ENV",
    "RERANKER_PROVIDER",
    "RERANKER_MODEL",
    "RERANKER_ENABLED",
    "RERANKER_UPSTREAM_URL",
    "RERANKER_UPSTREAM_API_KEY",
]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in _ENV:
        monkeypatch.delenv(name, raising=False)


def make_settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


@pytest.fixture
def local_settings() -> Settings:
    return make_settings()


@pytest.fixture
def cloud_settings() -> Settings:
    return make_settings(
        embeddings_provider="openai_compatible",
        embeddings_model="text-embedding-3-large",
        embedding_dim=4,
        embeddings_upstream_base_url="https://api.openai.example/v1",
        embeddings_upstream_api_key="sk-upstream",
        embeddings_request_extra_json='{"dimensions": 4}',
        internal_api_secret="s" * 40,
        embeddings_retry_backoff_base_seconds=0.0,
        embeddings_retry_backoff_max_seconds=0.0,
        sparse_enabled=False,
    )


def pytest_collection_modifyitems(config, items):
    import os

    if os.environ.get("EMBEDDINGS_MODEL_TESTS") == "1":
        return
    skip = pytest.mark.skip(reason="real ONNX models: set EMBEDDINGS_MODEL_TESTS=1")
    for item in items:
        if "model" in item.keywords:
            item.add_marker(skip)
