# SPDX-License-Identifier: Apache-2.0

import asyncio
import json

import httpx
import pytest
import respx

from raggie_embeddings.providers.openai_compat import (
    OpenAICompatDense,
    SlotPool,
    UpstreamError,
    split_batches,
)

URL = "https://api.openai.example/v1/embeddings"


def _ok(request: httpx.Request, *, dim: int = 4, reverse: bool = False) -> httpx.Response:
    inputs = json.loads(request.content)["input"]
    data = [
        {"object": "embedding", "index": i, "embedding": [float(i)] + [0.5] * (dim - 1)}
        for i in range(len(inputs))
    ]
    if reverse:
        data.reverse()
    return httpx.Response(
        200, json={"data": data, "usage": {"prompt_tokens": 3, "total_tokens": 3}}
    )


async def _provider(cfg, sleeps: list[float] | None = None) -> OpenAICompatDense:
    async def fake_sleep(seconds: float) -> None:
        if sleeps is not None:
            sleeps.append(seconds)

    return OpenAICompatDense(cfg, httpx.AsyncClient(), sleep=fake_sleep, rng=lambda: 1.0)


@respx.mock
async def test_openai_shape_request_and_index_ordering(cloud_settings) -> None:
    route = respx.post(URL).mock(side_effect=lambda r: _ok(r, reverse=True))
    provider = await _provider(cloud_settings)

    vectors = await provider.embed(["a", "b", "c"], "passage")

    assert [v[0] for v in vectors] == [0.0, 1.0, 2.0]  # sorted by index, not arrival
    request = route.calls.last.request
    assert request.headers["authorization"] == "Bearer sk-upstream"
    body = json.loads(request.content)
    assert body == {"model": "text-embedding-3-large", "input": ["a", "b", "c"], "dimensions": 4}


@respx.mock
async def test_extra_json_merge_and_prefixes(cloud_settings) -> None:
    cfg = cloud_settings.model_copy(
        update={
            "embeddings_request_extra_json": '{"dimensions": 4, "encoding_format": "float"}',
            "embeddings_query_extra_json": '{"input_type": "query", "dimensions": 4}',
            "embeddings_passage_extra_json": '{"input_type": "document"}',
            "embeddings_query_prefix": "Q> ",
            "embeddings_passage_prefix": "P> ",
        }
    )
    route = respx.post(URL).mock(side_effect=_ok)
    provider = await _provider(cfg)

    await provider.embed(["hello"], "query")
    query_body = json.loads(route.calls.last.request.content)
    await provider.embed(["doc"], "passage")
    passage_body = json.loads(route.calls.last.request.content)

    assert query_body == {
        "model": "text-embedding-3-large",
        "input": ["Q> hello"],
        "dimensions": 4,
        "encoding_format": "float",
        "input_type": "query",
    }
    assert passage_body["input"] == ["P> doc"]
    assert passage_body["input_type"] == "document"


@respx.mock
async def test_extras_cannot_override_input(cloud_settings) -> None:
    cfg = cloud_settings.model_copy(update={"embeddings_request_extra_json": '{"input": "x"}'})
    route = respx.post(URL).mock(side_effect=_ok)
    await (await _provider(cfg)).embed(["real"], "passage")
    assert json.loads(route.calls.last.request.content)["input"] == ["real"]


@respx.mock
async def test_150_inputs_make_three_calls(cloud_settings) -> None:
    route = respx.post(URL).mock(side_effect=_ok)
    provider = await _provider(cloud_settings)

    vectors = await provider.embed([f"t{i}" for i in range(150)], "passage")

    assert route.call_count == 3
    sizes = sorted(len(json.loads(c.request.content)["input"]) for c in route.calls)
    assert sizes == [22, 64, 64]
    assert len(vectors) == 150


def test_batches_also_split_on_characters() -> None:
    texts = ["x" * 90_000, "y" * 90_000, "z" * 90_000, "w"]
    batches = split_batches(texts, max_items=64, max_chars=200_000)
    assert [len(b) for b in batches] == [2, 2]
    assert [i for batch in batches for i, _ in batch] == [0, 1, 2, 3]


@respx.mock
async def test_inputs_are_truncated(cloud_settings) -> None:
    cfg = cloud_settings.model_copy(update={"embeddings_max_input_chars": 10})
    route = respx.post(URL).mock(side_effect=_ok)
    await (await _provider(cfg)).embed(["0123456789ABCDEF"], "passage")
    assert json.loads(route.calls.last.request.content)["input"] == ["0123456789"]


@respx.mock
async def test_passage_retries_honour_retry_after_then_succeed(cloud_settings) -> None:
    route = respx.post(URL).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "2"}),
            httpx.Response(503),
            _ok,
        ]
    )
    sleeps: list[float] = []
    provider = await _provider(
        cloud_settings.model_copy(
            update={
                "embeddings_retry_backoff_base_seconds": 0.5,
                "embeddings_retry_backoff_max_seconds": 30.0,
            }
        ),
        sleeps,
    )

    vectors = await provider.embed(["a"], "passage")

    assert len(vectors) == 1
    assert route.call_count == 3
    assert sleeps[0] == 2.0  # Retry-After honoured
    assert sleeps[1] == 1.0  # full jitter (rng=1.0) of base * 2**1


@respx.mock
async def test_passage_exhaustion_surfaces_429_with_retry_after(cloud_settings) -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(429, headers={"Retry-After": "7"}))
    provider = await _provider(
        cloud_settings.model_copy(update={"embeddings_retry_backoff_max_seconds": 30.0})
    )

    with pytest.raises(UpstreamError) as excinfo:
        await provider.embed(["a"], "passage")

    assert route.call_count == 1 + cloud_settings.embeddings_passage_retries
    assert excinfo.value.status_code == 429
    assert excinfo.value.retry_after == 7


@respx.mock
async def test_passage_5xx_exhaustion_also_asks_caller_to_back_off(cloud_settings) -> None:
    respx.post(URL).mock(return_value=httpx.Response(502))
    with pytest.raises(UpstreamError) as excinfo:
        await (await _provider(cloud_settings)).embed(["a"], "passage")
    assert excinfo.value.status_code == 429
    assert excinfo.value.retry_after >= 1


@respx.mock
async def test_query_retries_once(cloud_settings) -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(500))
    with pytest.raises(UpstreamError) as excinfo:
        await (await _provider(cloud_settings)).embed(["q"], "query")
    assert route.call_count == 2  # 1 attempt + 1 retry
    assert excinfo.value.status_code == 503


@respx.mock
async def test_query_timeout_is_retried_then_fails(cloud_settings) -> None:
    route = respx.post(URL).mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(UpstreamError) as excinfo:
        await (await _provider(cloud_settings)).embed(["q"], "query")
    assert route.call_count == 2
    assert excinfo.value.status_code == 503


@pytest.mark.parametrize("status", [400, 401, 403, 404])
@respx.mock
async def test_client_errors_are_not_retried(cloud_settings, status: int) -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(status, json={"error": "nope"}))
    with pytest.raises(UpstreamError) as excinfo:
        await (await _provider(cloud_settings)).embed(["a"], "passage")
    assert route.call_count == 1
    assert excinfo.value.status_code == 502
    assert str(status) in excinfo.value.detail
    hint = "check EMBEDDINGS_UPSTREAM_API_KEY in .env.embeddings"
    assert (hint in excinfo.value.detail) == (status in (401, 403))


@respx.mock
async def test_dimension_mismatch_is_an_error(cloud_settings) -> None:
    respx.post(URL).mock(side_effect=lambda r: _ok(r, dim=3))
    with pytest.raises(UpstreamError, match="3-dimensional"):
        await (await _provider(cloud_settings)).embed(["a"], "passage")


@respx.mock
async def test_count_mismatch_is_an_error(cloud_settings) -> None:
    respx.post(URL).mock(
        return_value=httpx.Response(200, json={"data": [{"index": 0, "embedding": [1, 2, 3, 4]}]})
    )
    with pytest.raises(UpstreamError, match="returned 1 embeddings for 2 inputs"):
        await (await _provider(cloud_settings)).embed(["a", "b"], "passage")


@respx.mock
async def test_upstream_key_is_never_echoed(cloud_settings) -> None:
    respx.post(URL).mock(return_value=httpx.Response(401, text="bad key sk-upstream"))
    with pytest.raises(UpstreamError) as excinfo:
        await (await _provider(cloud_settings)).embed(["a"], "passage")
    assert "sk-upstream" not in excinfo.value.detail


async def test_slot_pool_reserves_slots_for_queries() -> None:
    pool = SlotPool(total=3, reserved=1)
    release = asyncio.Event()
    passages_running = 0

    async def passage() -> None:
        nonlocal passages_running
        async with pool.slot(priority=False):
            passages_running += 1
            await release.wait()

    tasks = [asyncio.create_task(passage()) for _ in range(5)]
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert passages_running == 2  # only the general slots

    # A query still gets through while passages saturate their share.
    async with pool.slot(priority=True):
        pass

    release.set()
    await asyncio.gather(*tasks)
    assert passages_running == 5
