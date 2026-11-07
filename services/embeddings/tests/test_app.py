# SPDX-License-Identifier: Apache-2.0

import fakeredis.aioredis
import httpx
import pytest
import respx
from conftest import make_settings
from fakes import (
    FakeDenseModel,
    cloud_mock_app,
    local_stub_app,
    openai_upstream,
    wait_probe_failed,
    wait_ready,
)
from fastapi.testclient import TestClient

from raggie_embeddings.config import ConfigError
from raggie_embeddings.main import create_app

UPSTREAM = "https://api.openai.example/v1/embeddings"
AUTH = {"Authorization": "Bearer " + "s" * 40}


# ───────────────────────────── local (legacy) mode ─────────────────────────


def test_local_mode_keeps_legacy_contract_and_adds_collection(local_settings) -> None:
    dense = FakeDenseModel(1024)
    with TestClient(local_stub_app(local_settings, dense_model=dense)) as client:
        assert wait_ready(client).json() == {"status": "ready"}
        # No auth required locally (existing callers send arbitrary bearers).
        r = client.post("/v1/embeddings", json={"input": ["merhaba", "hello"]})
        assert r.status_code == 200
        body = r.json()
        assert body["object"] == "list"
        assert [d["index"] for d in body["data"]] == [0, 1]
        assert len(body["data"][0]["embedding"]) == 1024
        assert body["model"] == "intfloat/multilingual-e5-large"
        assert body["collection"] == "raggie_chunks_d1024"
        assert body["fingerprint"] == "2872ae6a"
        assert dense.calls[-1] == ["passage: merhaba", "passage: hello"]

        q = client.post("/v1/query", json={"query": "izin politikası"}).json()
        assert dense.calls[-1] == ["query: izin politikası"]
        assert q["collection"] == "raggie_chunks_d1024"
        assert q["sparse"] == {"indices": [7], "values": [1.0]}


def test_local_mode_requires_the_bearer_once_a_secret_is_set(local_settings) -> None:
    # A configured INTERNAL_API_SECRET turns auth on in local mode too (every
    # caller already sends it); EMBEDDINGS_REQUIRE_AUTH=false opts back out.
    cfg = local_settings.model_copy(update={"internal_api_secret": "s" * 40})
    with TestClient(local_stub_app(cfg)) as client:
        wait_ready(client)
        assert client.post("/v1/query", json={"query": "a"}).status_code == 401
        assert client.get("/v1/info").status_code == 401
        assert client.post("/v1/query", json={"query": "a"}, headers=AUTH).status_code == 200
        assert client.get("/healthz").status_code == 200
    opted_out = cfg.model_copy(update={"embeddings_require_auth": False})
    with TestClient(local_stub_app(opted_out)) as client:
        wait_ready(client)
        assert client.get("/v1/info").status_code == 200


def test_single_string_and_unknown_input_type_are_passages(local_settings) -> None:
    dense = FakeDenseModel(1024)
    with TestClient(local_stub_app(local_settings, dense_model=dense)) as client:
        r = client.post("/v1/embeddings", json={"input": "tek", "input_type": "document"})
        assert r.status_code == 200
        assert len(r.json()["data"]) == 1
        assert dense.calls[-1] == ["passage: tek"]


def test_info_local(local_settings) -> None:
    with TestClient(local_stub_app(local_settings)) as client:
        assert client.get("/v1/info").json() == {
            "provider": "local",
            "model": "intfloat/multilingual-e5-large",
            "dim": 1024,
            "fingerprint": "2872ae6a",
            "collection": "raggie_chunks_d1024",
            "sparse_model": "Qdrant/bm25",
            "reranker": {
                "provider": "local",
                "model": "Alibaba-NLP/gte-multilingual-reranker-base",
            },
            "egress": {"dense_host": None, "rerank_host": None},
        }


def test_rerank_local_orders_and_truncates_top_n(local_settings) -> None:
    with TestClient(local_stub_app(local_settings)) as client:
        r = client.post(
            "/v1/rerank", json={"query": "q", "documents": ["aa", "a", "aaaa"], "top_n": 2}
        )
        assert r.json() == {"results": [{"index": 2, "score": 4.0}, {"index": 0, "score": 2.0}]}
        assert client.post("/v1/rerank", json={"query": "q", "documents": []}).json() == {
            "results": []
        }


def test_rerank_none_returns_identity(local_settings) -> None:
    cfg = local_settings.model_copy(update={"reranker_enabled": False})
    with TestClient(local_stub_app(cfg)) as client:
        assert client.get("/v1/info").json()["reranker"] == {"provider": "none", "model": None}
        results = client.post(
            "/v1/rerank", json={"query": "q", "documents": ["a", "bbb", "cc"]}
        ).json()["results"]
        assert [r["index"] for r in results] == [0, 1, 2]


def test_local_dimension_mismatch_keeps_readyz_503(local_settings) -> None:
    with TestClient(local_stub_app(local_settings, dim=768)) as client:
        r = wait_probe_failed(client)
        assert r.status_code == 503
        assert r.json()["status"] == "not_ready"
        assert "768" in r.json()["reason"] and "EMBEDDING_DIM=1024" in r.json()["reason"]


# ───────────────────────────────── cloud mode ──────────────────────────────


@respx.mock
def test_cloud_mode_routes_dense_upstream_and_never_loads_local_model(
    cloud_settings, monkeypatch
) -> None:
    import raggie_embeddings.providers.local as local_module

    def boom(*_a, **_k):
        raise AssertionError("cloud mode must not load the dense TextEmbedding model")

    monkeypatch.setattr(local_module.LocalDense, "load", boom)
    respx.post(UPSTREAM).mock(side_effect=lambda r: openai_upstream(r, dim=4))
    with TestClient(cloud_mock_app(cloud_settings)) as client:
        assert wait_ready(client).status_code == 200
        r = client.post("/v1/embeddings", json={"input": ["a", "b"]}, headers=AUTH)
        assert r.status_code == 200
        assert r.json()["collection"].startswith("raggie_chunks_d4_")
        info = client.get("/v1/info", headers=AUTH).json()
        assert info["provider"] == "openai_compatible"
        assert info["egress"] == {"dense_host": "api.openai.example", "rerank_host": None}
        assert info["collection"] == r.json()["collection"]


@respx.mock
def test_cloud_requires_internal_bearer(cloud_settings) -> None:
    respx.post(UPSTREAM).mock(side_effect=lambda r: openai_upstream(r, dim=4))
    with TestClient(cloud_mock_app(cloud_settings)) as client:
        for path, body in (
            ("/v1/embeddings", {"input": "a"}),
            ("/v1/query", {"query": "a"}),
            ("/v1/sparse", {"input": "a"}),
            ("/v1/rerank", {"query": "a", "documents": ["x"]}),
        ):
            assert client.post(path, json=body).status_code == 401
            assert (
                client.post(path, json=body, headers={"Authorization": "Bearer wrong"}).status_code
                == 401
            )
        assert client.get("/v1/info").status_code == 401
        # Probes and metrics stay open for the orchestrator.
        assert client.get("/healthz").status_code == 200
        assert client.get("/metrics").status_code == 200


def test_cloud_without_secret_refuses_to_boot(cloud_settings) -> None:
    cfg = cloud_settings.model_copy(update={"internal_api_secret": ""})
    with pytest.raises(ConfigError, match="INTERNAL_API_SECRET"):
        with TestClient(cloud_mock_app(cfg)):
            pass


def test_invalid_extra_json_refuses_to_boot(cloud_settings) -> None:
    cfg = cloud_settings.model_copy(update={"embeddings_query_extra_json": "{not json"})
    with pytest.raises(ConfigError, match="EMBEDDINGS_QUERY_EXTRA_JSON"):
        with TestClient(cloud_mock_app(cfg)):
            pass


@respx.mock
def test_cloud_dimension_mismatch_readyz_503_then_recovers(cloud_settings) -> None:
    dims = {"value": 3}
    respx.post(UPSTREAM).mock(side_effect=lambda r: openai_upstream(r, dim=dims["value"]))
    cfg = cloud_settings.model_copy(update={"embeddings_probe_interval_seconds": 0.05})
    with TestClient(cloud_mock_app(cfg)) as client:
        r = wait_probe_failed(client)
        assert r.status_code == 503
        assert r.json()["status"] == "not_ready"
        assert "EMBEDDING_DIM=4" in r.json()["reason"]
        dims["value"] = 4  # operator fixes the upstream/model
        assert wait_ready(client).status_code == 200


@respx.mock
def test_cloud_upstream_down_readyz_503_with_reason(cloud_settings, caplog, monkeypatch) -> None:
    import logging

    import raggie_embeddings.main as main_module

    monkeypatch.setattr(main_module, "configure_logging", lambda level: None)
    respx.post(UPSTREAM).mock(return_value=httpx.Response(401))
    hint = "check EMBEDDINGS_UPSTREAM_API_KEY in .env.embeddings"
    with caplog.at_level(logging.WARNING, logger="raggie.embeddings"):
        with TestClient(cloud_mock_app(cloud_settings)) as client:
            r = wait_probe_failed(client)
            assert r.status_code == 503
            assert "401" in r.json()["reason"]
            assert hint in r.json()["reason"]
    assert any(
        "not ready" in rec.getMessage() and hint in rec.getMessage() for rec in caplog.records
    )


@respx.mock
def test_passage_429_is_passed_to_the_worker_with_retry_after(cloud_settings) -> None:
    calls = {"n": 0}

    def upstream(request):
        calls["n"] += 1
        if calls["n"] == 1:  # readiness probe
            return openai_upstream(request, dim=4)
        return httpx.Response(429, headers={"Retry-After": "9"})

    respx.post(UPSTREAM).mock(side_effect=upstream)
    with TestClient(cloud_mock_app(cloud_settings)) as client:
        wait_ready(client)
        r = client.post("/v1/embeddings", json={"input": ["doc"]}, headers=AUTH)
        assert r.status_code == 429
        assert r.headers["retry-after"] == "9"
        assert "detail" in r.json()


@respx.mock
def test_upstream_client_error_is_502(cloud_settings) -> None:
    calls = {"n": 0}

    def upstream(request):
        calls["n"] += 1
        return openai_upstream(request, dim=4) if calls["n"] == 1 else httpx.Response(400)

    respx.post(UPSTREAM).mock(side_effect=upstream)
    with TestClient(cloud_mock_app(cloud_settings)) as client:
        wait_ready(client)
        r = client.post("/v1/query", json={"query": "q"}, headers=AUTH)
        assert r.status_code == 502


@respx.mock
def test_remote_rerank_failure_falls_back_to_identity(cloud_settings) -> None:
    cfg = cloud_settings.model_copy(
        update={
            "reranker_provider": "cohere",
            "reranker_model": "rerank-v3.5",
            "reranker_upstream_url": "https://api.cohere.example/v2/rerank",
        }
    )
    respx.post(UPSTREAM).mock(side_effect=lambda r: openai_upstream(r, dim=4))
    respx.post("https://api.cohere.example/v2/rerank").mock(return_value=httpx.Response(500))
    with TestClient(cloud_mock_app(cfg)) as client:
        r = client.post("/v1/rerank", json={"query": "q", "documents": ["a", "b"]}, headers=AUTH)
        assert r.status_code == 200
        assert [x["index"] for x in r.json()["results"]] == [0, 1]
        info = client.get("/v1/info", headers=AUTH).json()
        assert info["reranker"] == {"provider": "cohere", "model": "rerank-v3.5"}
        assert info["egress"]["rerank_host"] == "api.cohere.example"


# ───────────────────────────── query cache ─────────────────────────────────


@respx.mock
def test_query_embeddings_are_cached_per_fingerprint(cloud_settings) -> None:
    route = respx.post(UPSTREAM).mock(side_effect=lambda r: openai_upstream(r, dim=4))
    redis = fakeredis.aioredis.FakeRedis()
    with TestClient(cloud_mock_app(cloud_settings, redis=redis)) as client:
        wait_ready(client)
        before = route.call_count
        first = client.post("/v1/query", json={"query": "izin  politikası"}, headers=AUTH).json()
        second = client.post("/v1/query", json={"query": "izin politikası "}, headers=AUTH).json()
        assert route.call_count == before + 1  # second served from Redis
        assert first["dense"] == pytest.approx(second["dense"])
        # Passages are never cached.
        client.post("/v1/embeddings", json={"input": ["doc"]}, headers=AUTH)
        client.post("/v1/embeddings", json={"input": ["doc"]}, headers=AUTH)
        assert route.call_count == before + 3


def test_local_query_cache_and_fail_open(local_settings) -> None:
    dense = FakeDenseModel(1024)

    class Broken:
        async def get(self, *_a, **_k):
            raise ConnectionError("down")

        async def set(self, *_a, **_k):
            raise ConnectionError("down")

    with TestClient(local_stub_app(local_settings, dense_model=dense, redis=Broken())) as client:
        wait_ready(client)
        r = client.post("/v1/query", json={"query": "q"})
        assert r.status_code == 200  # Redis down never fails a query


def test_create_app_without_overrides_is_importable() -> None:
    # The module-level ASGI app used by uvicorn.
    from raggie_embeddings.main import app

    assert app.title == "Raggie Embeddings"
    assert create_app(make_settings()).title == "Raggie Embeddings"


def test_local_reranker_uses_configured_batch_size(local_settings) -> None:
    import asyncio

    from raggie_embeddings.providers.local import LocalReranker

    seen = {}

    class Encoder:
        def rerank(self, query, documents, batch_size=64):
            seen["batch_size"] = batch_size
            return [1.0 for _ in documents]

    cfg = local_settings.model_copy(update={"reranker_batch_size": 4})
    asyncio.run(LocalReranker(cfg, Encoder()).rerank("q", ["a", "b"]))
    assert seen["batch_size"] == 4


@respx.mock
def test_boot_log_states_profile_and_egress(cloud_settings, caplog, monkeypatch) -> None:
    import logging

    import raggie_embeddings.main as main_module

    # configure_logging swaps the root handlers, which would detach caplog.
    monkeypatch.setattr(main_module, "configure_logging", lambda level: None)
    respx.post(UPSTREAM).mock(side_effect=lambda r: openai_upstream(r, dim=4))
    with caplog.at_level(logging.INFO, logger="raggie.embeddings"):
        with TestClient(cloud_mock_app(cloud_settings)) as client:
            wait_ready(client)
    started = [r.getMessage() for r in caplog.records if "gateway starting" in r.getMessage()]
    assert started and "egress_dense_host=api.openai.example" in started[0]
    assert "sk-upstream" not in " ".join(r.getMessage() for r in caplog.records)


@pytest.mark.parametrize(("key", "warned"), [("", True), ("sk-upstream", False)])
@respx.mock
def test_cloud_boot_warns_when_upstream_key_is_empty(
    cloud_settings, caplog, monkeypatch, key, warned
) -> None:
    import logging

    import raggie_embeddings.main as main_module

    monkeypatch.setattr(main_module, "configure_logging", lambda level: None)
    respx.post(UPSTREAM).mock(side_effect=lambda r: openai_upstream(r, dim=4))
    cfg = cloud_settings.model_copy(update={"embeddings_upstream_api_key": key})
    with caplog.at_level(logging.WARNING, logger="raggie.embeddings"):
        with TestClient(cloud_mock_app(cfg)) as client:
            assert wait_ready(client).status_code == 200  # keyless TEI/vLLM still boots
    warnings = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING and "EMBEDDINGS_UPSTREAM_API_KEY is empty" in r.getMessage()
    ]
    assert bool(warnings) == warned
