# SPDX-License-Identifier: Apache-2.0

"""The infra gate itself: skip locally, fail under CI, never leak credentials."""

import socket

import pytest
from _infra import Dependency, InfraGate, host_port


class _Item:
    def __init__(self, fixturenames=(), markers=()) -> None:
        self.fixturenames = list(fixturenames)
        self._markers = {m: True for m in markers}

    def add_marker(self, marker) -> None:
        self._markers[marker.name] = True

    def get_closest_marker(self, name):
        return self._markers.get(name)


def _closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]  # closed again on exit: nothing listens


def _gate(url: str, *, optional: bool = False) -> InfraGate:
    return InfraGate(
        [
            Dependency(
                "postgres",
                "Postgres",
                "DATABASE_URL",
                lambda: url,
                frozenset({"pg_pool"}),
                optional=optional,
            )
        ]
    )


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("postgresql://u:secret@db.internal:6543/x", ("db.internal", 6543)),
        ("postgresql://u:secret@db/x", ("db", 5432)),
        ("redis://:pw@cache:6380/0", ("cache", 6380)),
        ("rediss://cache", ("cache", 6379)),
        ("http://localhost:56333", ("localhost", 56333)),
        ("s3.local:8333", ("s3.local", 8333)),
        ("", None),
        ("http://", None),
    ],
)
def test_host_port(url, expected) -> None:
    assert host_port(url) == expected


def test_fixture_usage_applies_the_marker() -> None:
    item = _Item(fixturenames=["pg_pool", "tmp_path"])
    _gate("postgresql://u:p@localhost:1/x").mark([item])
    assert item.get_closest_marker("requires_postgres")
    other = _Item(fixturenames=["tmp_path"])
    _gate("postgresql://u:p@localhost:1/x").mark([other])
    assert not other.get_closest_marker("requires_postgres")


def test_unreachable_skips_locally_with_reason_and_no_credentials(monkeypatch) -> None:
    monkeypatch.delenv("CI", raising=False)
    port = _closed_port()
    gate = _gate(f"postgresql://raggie:hunter2@127.0.0.1:{port}/x")
    with pytest.raises(pytest.skip.Exception) as excinfo:
        gate.check(_Item(markers=["requires_postgres"]))
    message = str(excinfo.value)
    assert f"Postgres not reachable at 127.0.0.1:{port}" in message
    assert "make test-deps-up" in message and "hunter2" not in message


@pytest.mark.parametrize("ci", ["true", "1", "TRUE"])
def test_unreachable_fails_under_ci(monkeypatch, ci) -> None:
    monkeypatch.setenv("CI", ci)
    gate = _gate(f"postgresql://u:p@127.0.0.1:{_closed_port()}/x")
    with pytest.raises(pytest.fail.Exception, match="CI=true"):
        gate.check(_Item(markers=["requires_postgres"]))


def test_reachable_runs(monkeypatch) -> None:
    monkeypatch.setenv("CI", "true")
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        port = server.getsockname()[1]
        _gate(f"postgresql://u:p@127.0.0.1:{port}/x").check(_Item(markers=["requires_postgres"]))


def test_unmarked_tests_are_never_probed(monkeypatch) -> None:
    monkeypatch.setenv("CI", "true")
    _gate("postgresql://u:p@127.0.0.1:1/x").check(_Item())


def test_probe_runs_once_per_session(monkeypatch) -> None:
    monkeypatch.delenv("CI", raising=False)
    calls = []
    real = socket.create_connection

    def counting(*args, **kwargs):
        calls.append(args)
        return real(*args, **kwargs)

    monkeypatch.setattr(socket, "create_connection", counting)
    gate = _gate(f"postgresql://u:p@127.0.0.1:{_closed_port()}/x")
    for _ in range(3):
        with pytest.raises(pytest.skip.Exception):
            gate.check(_Item(markers=["requires_postgres"]))
    assert len(calls) == 1


def test_optional_unconfigured_suite_skips_even_in_ci(monkeypatch) -> None:
    monkeypatch.setenv("CI", "true")
    with pytest.raises(pytest.skip.Exception, match="opt-in"):
        _gate("", optional=True).check(_Item(markers=["requires_postgres"]))


def test_required_but_unconfigured_fails_in_ci(monkeypatch) -> None:
    monkeypatch.setenv("CI", "true")
    with pytest.raises(pytest.fail.Exception, match="not configured"):
        _gate("").check(_Item(markers=["requires_postgres"]))
