# SPDX-License-Identifier: Apache-2.0

import httpx
import pytest

import raggie_workers.evaluation.judge as judge_module
import raggie_workers.main as main_module
from raggie_workers.config import Settings
from raggie_workers.evaluation.judge import FaithfulnessJudge


class _Response:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"choices": [{"message": {"content": "0.9"}}]}


def _recording_client(seen: list, *, raises: Exception | None = None):
    class _Client:
        def __init__(self, *, timeout):
            seen.append(timeout)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return None

        async def post(self, *_args, **_kwargs):
            if raises is not None:
                raise raises
            return _Response()

    return _Client


@pytest.mark.parametrize(
    ("raw", "want"), [(None, 30.0), ("300", 300.0), ("1", 5.0), ("5000", 900.0)]
)
def test_eval_llm_timeout_setting_is_bounded(monkeypatch, raw, want) -> None:
    if raw is None:
        monkeypatch.delenv("EVAL_LLM_TIMEOUT_SECONDS", raising=False)
    else:
        monkeypatch.setenv("EVAL_LLM_TIMEOUT_SECONDS", raw)
    assert Settings(_env_file=None).eval_llm_timeout_seconds == want


# EVAL_LLM_TIMEOUT_SECONDS is the judge's httpx budget, not a dead knob.
async def test_eval_llm_timeout_reaches_httpx(monkeypatch) -> None:
    monkeypatch.setenv("EVAL_LLM_TIMEOUT_SECONDS", "300")
    seen: list = []
    monkeypatch.setattr(judge_module.httpx, "AsyncClient", _recording_client(seen))
    judge = main_module.eval_judge(Settings(_env_file=None))
    assert await judge.score("Paris [1].", "Paris is the capital.") == 0.9
    assert seen == [300.0]


# A slow model that never answers inside the budget is "not scored", not an
# error: an error leaves the event pending, and XAUTOCLAIM would redeliver it
# to the same slow model forever.
async def test_judge_read_timeout_is_not_scored(monkeypatch) -> None:
    seen: list = []
    monkeypatch.setattr(
        judge_module.httpx,
        "AsyncClient",
        _recording_client(seen, raises=httpx.ReadTimeout("slow model")),
    )
    judge = FaithfulnessJudge("http://llm/v1", "k", "m", timeout=7.0)
    assert await judge.score("Paris [1].", "Paris is the capital.") is None
    assert seen == [7.0]


# Unreachable upstreams still raise, so the event is redelivered once it is back.
async def test_judge_connect_failure_still_raises(monkeypatch) -> None:
    monkeypatch.setattr(
        judge_module.httpx,
        "AsyncClient",
        _recording_client([], raises=httpx.ConnectError("down")),
    )
    judge = FaithfulnessJudge("http://llm/v1", "k", "m")
    with pytest.raises(httpx.ConnectError):
        await judge.score("Paris [1].", "Paris is the capital.")


class _SlowDrip(httpx.AsyncByteStream):
    """Each chunk arrives well inside httpx's per-read timeout, but the whole
    body takes far longer than the judge budget."""

    async def __aiter__(self):
        import asyncio

        body = b'{"choices": [{"message": {"content": "0.9"}}]}'
        for byte in body:
            await asyncio.sleep(0.05)
            yield bytes([byte])


def _slow_drip_client():
    real = httpx.AsyncClient

    def factory(*, timeout):
        transport = httpx.MockTransport(lambda _req: httpx.Response(200, stream=_SlowDrip()))
        return real(timeout=timeout, transport=transport)

    return factory


# httpx timeouts are per phase (connect/read/write), so a trickling upstream never
# trips them. The judge's budget caps the whole call; past it the answer is left
# unscored (None → acked), exactly like a read timeout.
async def test_judge_budget_caps_a_slow_drip_upstream(monkeypatch) -> None:
    import time

    monkeypatch.setattr(judge_module.httpx, "AsyncClient", _slow_drip_client())
    judge = FaithfulnessJudge("http://llm/v1", "k", "m", timeout=0.5)
    start = time.monotonic()
    assert await judge.score("Paris [1].", "Paris is the capital.") is None
    assert time.monotonic() - start < 1.5  # the body alone would take ~2.4 s
