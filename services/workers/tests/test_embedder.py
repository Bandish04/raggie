# SPDX-License-Identifier: Apache-2.0

import json

import httpx

from raggie_workers.ingestion.openai_embedder import OpenAICompatibleEmbedder


async def test_embed_parses_and_orders_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        # Return out of order to verify the adapter sorts by index.
        n = len(body["input"])
        data = [{"index": n - 1 - i, "embedding": [float(n - 1 - i)]} for i in range(n)]
        return httpx.Response(200, json={"model": body["model"], "data": data})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    emb = OpenAICompatibleEmbedder(
        base_url="http://llmaas/v1", api_key="k", model="m", client=client
    )
    out = await emb.embed(["a", "b", "c"])
    assert out == [[0.0], [1.0], [2.0]]
    await emb.aclose()


async def test_embed_retries_on_503_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0]}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    emb = OpenAICompatibleEmbedder(
        base_url="http://llmaas/v1", api_key="k", model="m", client=client, max_retries=5
    )
    out = await emb.embed(["x"])
    assert out == [[1.0]]
    assert calls["n"] == 3
    await emb.aclose()


async def test_embed_empty_is_noop() -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    emb = OpenAICompatibleEmbedder(base_url="http://x/v1", api_key="k", model="m", client=client)
    assert await emb.embed([]) == []
    await emb.aclose()
