# SPDX-License-Identifier: Apache-2.0

import json

import httpx
import pytest

from raggie_workers.ingestion.openai_embedder import (
    EmbedResult,
    FingerprintMismatch,
    OpenAICompatibleEmbedder,
)

BASE = "http://embeddings:8002/v1"


def _ok(
    request: httpx.Request, *, fp: str = "2872ae6a", collection: str = "raggie_chunks_d1024"
) -> httpx.Response:
    inputs = json.loads(request.content)["input"]
    return httpx.Response(
        200,
        json={
            "object": "list",
            "data": [
                {"object": "embedding", "index": i, "embedding": [float(i), 0.5]}
                for i in reversed(range(len(inputs)))
            ],
            "model": "m",
            "usage": {"prompt_tokens": 1, "total_tokens": 1},
            "collection": collection,
            "fingerprint": fp,
        },
    )


def _embedder(handler, sleeps=None, **kw) -> OpenAICompatibleEmbedder:
    async def fake_sleep(seconds: float) -> None:
        if sleeps is not None:
            sleeps.append(seconds)

    return OpenAICompatibleEmbedder(
        base_url=BASE,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        sleep=fake_sleep,
        **kw,
    )


async def test_passage_input_type_bearer_and_profile() -> None:
    seen = []

    def handler(request):
        seen.append(request)
        return _ok(request)

    result = await _embedder(handler, api_key="s" * 40).embed_with_profile(["a", "b"])
    assert isinstance(result, EmbedResult)
    assert result.vectors == [[0.0, 0.5], [1.0, 0.5]]  # sorted by index
    assert (result.fingerprint, result.collection) == ("2872ae6a", "raggie_chunks_d1024")
    body = json.loads(seen[0].content)
    assert body == {"input": ["a", "b"], "input_type": "passage"}
    assert seen[0].headers["authorization"] == "Bearer " + "s" * 40


async def test_no_secret_sends_no_authorization_header() -> None:
    seen = []

    def handler(request):
        seen.append(request)
        return _ok(request)

    assert await _embedder(handler).embed(["a"]) == [[0.0, 0.5]]
    assert "authorization" not in seen[0].headers


async def test_retry_after_from_the_gateway_is_honoured() -> None:
    responses = iter(
        [
            httpx.Response(429, headers={"Retry-After": "17"}, json={"detail": "retry later"}),
            httpx.Response(503),
        ]
    )

    def handler(request):
        return next(responses, None) or _ok(request)

    sleeps: list[float] = []
    await _embedder(handler, sleeps).embed(["a"])
    assert sleeps[0] == 17.0
    assert len(sleeps) == 2  # 5xx used the exponential backoff


async def test_gives_up_after_max_retries() -> None:
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(429, headers={"Retry-After": "1"})

    with pytest.raises(httpx.HTTPStatusError):
        await _embedder(handler, max_retries=6).embed(["a"])
    assert len(calls) == 7  # first attempt + 6 retries


@pytest.mark.parametrize("status", [400, 401, 403, 422])
async def test_client_errors_are_not_retried(status: int) -> None:
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(status, json={"detail": "no"})

    with pytest.raises(httpx.HTTPStatusError):
        await _embedder(handler).embed(["a"])
    assert len(calls) == 1


async def test_expected_fingerprint_mismatch_is_terminal() -> None:
    with pytest.raises(FingerprintMismatch, match="aaaa1111.*2872ae6a"):
        await _embedder(_ok).embed_with_profile(["a"], expected_fingerprint="aaaa1111")


async def test_legacy_gateway_without_fingerprint_is_accepted() -> None:
    def handler(request):
        response = _ok(request)
        body = json.loads(response.content)
        body.pop("fingerprint"), body.pop("collection")
        return httpx.Response(200, json=body)

    result = await _embedder(handler).embed_with_profile(["a"], expected_fingerprint="aaaa1111")
    assert result.fingerprint is None and result.collection is None
