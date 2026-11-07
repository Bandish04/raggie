# SPDX-License-Identifier: Apache-2.0

"""reindex_all ordering and failure handling, without Postgres/Redis: the lock is
taken before the profile is stored, a lost compare-and-set stops the run, and a
mid-loop failure is audited with the partial result and exits non-zero."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from raggie_control_plane import reindex
from raggie_control_plane.embeddings_profile import ReembedBusyError

GW_FP = "5e1f00d2"


class FakeConn:
    """Never queried directly: the repositories and the lease are stubbed."""

    def __init__(self, calls: list[str], *, lock: bool = True) -> None:
        self.calls = calls
        self.lock = lock


class FakeProfile:
    def __init__(self, calls: list[str], *, changed: bool = True) -> None:
        self.calls = calls
        self.changed = changed
        info = SimpleNamespace(fingerprint=GW_FP, collection=f"raggie_chunks_d1024_{GW_FP}")

        async def get(force: bool = False):
            return info

        self.client = SimpleNamespace(get=get)

    async def store(self, conn, info, *, expected, reason):
        self.calls.append("store")
        return self.changed


@pytest.fixture
def world(monkeypatch):
    """Stub the repositories, the per-workspace job and the ingest target."""
    state = {"stored": ["2872ae6a"], "audits": [], "fail_on": None, "calls": []}

    class Settings:
        def __init__(self, conn) -> None:
            pass

        async def get_embedding_profile(self):
            state["calls"].append("get_profile")
            return state["stored"].pop(0) if len(state["stored"]) > 1 else state["stored"][0], None

    class Workspaces:
        def __init__(self, conn) -> None:
            pass

        async def list_all(self):
            return [SimpleNamespace(id=i) for i in (1, 2, 3)]

    class Audit:
        def __init__(self, conn) -> None:
            pass

        async def record(self, action, *, target=None, metadata=None, **_kw):
            state["audits"].append((action, target, metadata))

    @asynccontextmanager
    async def reembed_lease(conn):
        state["calls"].append("lock")
        if not conn.lock:
            raise ReembedBusyError("a re-embed is already running")
        try:
            yield SimpleNamespace(keep_alive=_noop)
        finally:
            state["calls"].append("unlock")

    async def _noop():
        return None

    async def reindex_workspace(conn, publisher, ws, target, *, keep_alive=None):
        state["calls"].append(f"ws{ws.id}")
        if state["fail_on"] == ws.id:
            raise RuntimeError("redis went away")
        return {"reindexed": 2, "skipped": 1}

    monkeypatch.setattr(reindex, "SettingsRepo", Settings)
    monkeypatch.setattr(reindex, "WorkspaceRepo", Workspaces)
    monkeypatch.setattr(reindex, "AuditRepo", Audit)
    monkeypatch.setattr(reindex, "reindex_workspace", reindex_workspace)
    monkeypatch.setattr(reindex, "reembed_lease", reembed_lease)
    monkeypatch.setattr(reindex.IngestTarget, "of", staticmethod(lambda info: info))
    return state


async def test_lock_is_taken_before_the_profile_is_stored(world) -> None:
    calls = world["calls"]
    result = await reindex.reindex_all(FakeConn(calls), None, FakeProfile(calls))
    assert calls.index("lock") < calls.index("store")
    assert calls[-1] == "unlock"
    assert result["reindexed"] == 6 and result["workspaces"] == 3


async def test_busy_lock_stores_nothing(world) -> None:
    calls = world["calls"]
    with pytest.raises(reindex.ReindexBusyError):
        await reindex.reindex_all(FakeConn(calls, lock=False), None, FakeProfile(calls))
    assert "store" not in calls


async def test_a_lost_compare_and_set_stops_the_run(world) -> None:
    # Someone else stored another profile between our read and our write.
    world["stored"] = ["2872ae6a", "deadbeef"]
    calls = world["calls"]
    with pytest.raises(reindex.ReindexConflictError):
        await reindex.reindex_all(FakeConn(calls), None, FakeProfile(calls, changed=False))
    assert not any(c.startswith("ws") for c in calls)
    assert calls[-1] == "unlock"


async def test_an_already_accepted_profile_is_not_a_conflict(world) -> None:
    world["stored"] = [GW_FP]
    calls = world["calls"]
    result = await reindex.reindex_all(FakeConn(calls), None, FakeProfile(calls, changed=False))
    assert result["reindexed"] == 6


async def test_a_mid_loop_failure_is_audited_with_the_partial_result(world) -> None:
    world["fail_on"] = 2
    calls = world["calls"]
    with pytest.raises(reindex.ReindexPartialError) as exc:
        await reindex.reindex_all(FakeConn(calls), None, FakeProfile(calls))
    partial = exc.value.result
    assert partial["reindexed"] == 2 and partial["workspaces_done"] == 1
    assert partial["error"] == "RuntimeError"
    assert calls[-1] == "unlock"
    action, target, metadata = world["audits"][-1]
    assert target == GW_FP and metadata["partial"] is True and metadata["reindexed"] == 2


async def test_run_exits_non_zero_without_a_traceback(world, capsys) -> None:
    world["fail_on"] = 1
    calls = world["calls"]
    rc = await reindex.run(FakeConn(calls), None, FakeProfile(calls))
    err = capsys.readouterr().err
    assert rc == 1
    assert "reindex: stopped" in err and "Traceback" not in err
    assert '"partial": true' in err
