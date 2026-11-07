# SPDX-License-Identifier: Apache-2.0

import json

import httpx
import pytest
import respx
from conftest import make_settings

from raggie_embeddings.providers.rerank_remote import RemoteReranker, RerankError

URL = "https://rerank.example/v1/rerank"


def _reranker(provider: str, **overrides) -> RemoteReranker:
    cfg = make_settings(
        reranker_provider=provider,
        reranker_model="rerank-model-1",
        reranker_upstream_url=URL,
        reranker_upstream_api_key="rk-secret",
        **overrides,
    )
    return RemoteReranker(cfg, httpx.AsyncClient())


@respx.mock
async def test_cohere_dialect() -> None:
    route = respx.post(URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {"index": 1, "relevance_score": 0.9},
                    {"index": 0, "relevance_score": 0.2},
                ]
            },
        )
    )
    scores = await _reranker("cohere").rerank("q", ["a", "b"])
    assert scores == [0.2, 0.9]
    request = route.calls.last.request
    assert request.headers["authorization"] == "Bearer rk-secret"
    assert json.loads(request.content) == {
        "model": "rerank-model-1",
        "query": "q",
        "documents": ["a", "b"],
        "top_n": 2,
    }


@respx.mock
async def test_voyage_dialect() -> None:
    route = respx.post(URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [{"index": 0, "relevance_score": 0.7}, {"index": 1, "relevance_score": 0.1}]
            },
        )
    )
    assert await _reranker("voyage").rerank("q", ["a", "b"]) == [0.7, 0.1]
    assert json.loads(route.calls.last.request.content) == {
        "model": "rerank-model-1",
        "query": "q",
        "documents": ["a", "b"],
        "top_k": 2,
    }


@respx.mock
async def test_tei_dialect() -> None:
    route = respx.post(URL).mock(
        return_value=httpx.Response(
            200, json=[{"index": 1, "score": 3.5}, {"index": 0, "score": -1.0}]
        )
    )
    assert await _reranker("tei").rerank("q", ["a", "b"]) == [-1.0, 3.5]
    body = json.loads(route.calls.last.request.content)
    assert body == {"query": "q", "texts": ["a", "b"], "truncate": True}


@respx.mock
async def test_documents_are_truncated() -> None:
    route = respx.post(URL).mock(
        return_value=httpx.Response(200, json={"results": [{"index": 0, "relevance_score": 1}]})
    )
    await _reranker("cohere", reranker_max_doc_chars=5).rerank("q", ["abcdefghij"])
    assert json.loads(route.calls.last.request.content)["documents"] == ["abcde"]


@respx.mock
async def test_missing_results_rank_last() -> None:
    respx.post(URL).mock(
        return_value=httpx.Response(200, json={"results": [{"index": 2, "relevance_score": 0.5}]})
    )
    scores = await _reranker("cohere").rerank("q", ["a", "b", "c"])
    assert scores[2] == 0.5
    assert scores[0] < 0.5 and scores[1] < 0.5


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500),
        httpx.Response(429, headers={"Retry-After": "1"}),
        httpx.Response(200, json={"unexpected": True}),
        httpx.Response(200, text="not json"),
    ],
)
@respx.mock
async def test_failures_raise_without_retry(response: httpx.Response) -> None:
    route = respx.post(URL).mock(return_value=response)
    with pytest.raises(RerankError):
        await _reranker("cohere").rerank("q", ["a"])
    assert route.call_count == 1


@pytest.mark.parametrize("status", [401, 403])
@respx.mock
async def test_auth_failure_names_the_key_to_check(status: int) -> None:
    respx.post(URL).mock(return_value=httpx.Response(status, text="bad key rk-secret"))
    with pytest.raises(RerankError) as excinfo:
        await _reranker("cohere").rerank("q", ["a"])
    assert "check RERANKER_UPSTREAM_API_KEY in .env.embeddings" in str(excinfo.value)
    assert "rk-secret" not in str(excinfo.value)


@respx.mock
async def test_timeout_raises() -> None:
    respx.post(URL).mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(RerankError):
        await _reranker("voyage").rerank("q", ["a"])
