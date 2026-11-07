# SPDX-License-Identifier: Apache-2.0

import uuid

import httpx

import raggie_workers.scheduler as scheduler


def _task() -> dict:
    return {
        "id": uuid.uuid4(),
        "org_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "workspace_id": uuid.uuid4(),
        "name": "daily digest",
        "prompt": "summarize",
        "web_search": False,
        "deep_search": False,
        "model": None,
        "answer_style": None,
        "owner_locale": "tr",
    }


class _Client:
    def __init__(self, raises: Exception | None = None):
        self.raises = raises
        self.timeouts: list = []

    async def post(self, *_args, timeout, **_kwargs):
        self.timeouts.append(timeout)
        if self.raises is not None:
            raise self.raises
        return httpx.Response(200, json={"answer": "done"})


def _capture_results(monkeypatch) -> list[dict]:
    results: list[dict] = []

    async def persist(_pool, _task, *, status, body):
        results.append({"status": status, "body": body})

    monkeypatch.setattr(scheduler, "_persist_result", persist)
    return results


# SCHEDULER_TASK_TIMEOUT_SECONDS is the run-task budget, not a dead knob.
async def test_task_timeout_setting_reaches_httpx(monkeypatch) -> None:
    monkeypatch.setattr(scheduler.settings, "scheduler_task_timeout_seconds", 420.0)
    results = _capture_results(monkeypatch)
    client = _Client()
    await scheduler._execute_task(client, None, _task())
    assert client.timeouts == [420.0]
    assert results == [{"status": "ok", "body": "done"}]


# A run the scheduler gives up on ends as a recorded failure (last_status
# 'error' + a notification), never as a run left in flight.
async def test_task_timeout_is_recorded_as_failed(monkeypatch) -> None:
    results = _capture_results(monkeypatch)
    client = _Client(raises=httpx.ReadTimeout("slow edge"))
    await scheduler._execute_task(client, None, _task())
    assert len(results) == 1
    assert results[0]["status"] == "error"
    assert "zaman aşımına uğradı" in results[0]["body"]
