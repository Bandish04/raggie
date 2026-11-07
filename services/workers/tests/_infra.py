# SPDX-License-Identifier: Apache-2.0

"""Infra-aware test gating: tests that need Postgres / Redis / Qdrant / S3.

A contributor without the disposable test datastores gets clean SKIPs with a
reason instead of a wall of connection errors; under CI (``CI=true``) a missing
datastore FAILS the test instead, so an infra regression can never hide behind
a skip.

Markers ``requires_<name>`` are registered here and applied automatically to
every test whose fixture closure contains one of the dependency's fixtures;
tests that reach a datastore without such a fixture carry the marker
explicitly. Reachability is a fast TCP connect (0.5 s), probed once per
session per dependency. Reasons name host:port only, never credentials.

An *optional* dependency whose endpoint is not configured at all (e.g. the S3
tests behind OBJECTSTORE_TEST_ENDPOINT) is an opt-in suite: it is skipped
everywhere, CI included.
"""

from __future__ import annotations

import os
import socket
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from urllib.parse import urlsplit

import pytest

_CONNECT_TIMEOUT_SECONDS = 0.5
_HINT = "run `make test-deps-up` or rely on CI"
_DEFAULT_PORTS = {
    "postgres": 5432,
    "postgresql": 5432,
    "redis": 6379,
    "rediss": 6379,
    "http": 80,
    "https": 443,
}


def in_ci() -> bool:
    return os.environ.get("CI", "").strip().lower() in {"1", "true", "yes"}


def host_port(url: str) -> tuple[str, int] | None:
    """(host, port) of a datastore URL; bare ``host:port`` endpoints work too."""
    raw = url.strip()
    if not raw:
        return None
    if "://" not in raw:
        raw = f"tcp://{raw}"
    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError:
        return None
    if not parts.hostname:
        return None
    return parts.hostname, port or _DEFAULT_PORTS.get(parts.scheme, 0)


@dataclass(frozen=True)
class Dependency:
    name: str  # marker suffix: requires_<name>
    label: str  # human name in skip reasons
    env: str  # variable that configures the endpoint (for messages)
    url: Callable[[], str]  # resolved lazily (conftest may set defaults)
    fixtures: frozenset[str]
    optional: bool = False


class InfraGate:
    def __init__(self, dependencies: Iterable[Dependency]) -> None:
        self.dependencies = tuple(dependencies)
        self._cache: dict[str, str | None] = {}

    def configure(self, config: pytest.Config) -> None:
        for dep in self.dependencies:
            config.addinivalue_line(
                "markers",
                f"requires_{dep.name}: needs a reachable {dep.label} ({dep.env}); "
                "skipped when unreachable, fails under CI=true",
            )

    def mark(self, items: list[pytest.Item]) -> None:
        for item in items:
            names = set(getattr(item, "fixturenames", ()))
            for dep in self.dependencies:
                if names & dep.fixtures:
                    item.add_marker(getattr(pytest.mark, f"requires_{dep.name}"))

    def _problem(self, dep: Dependency) -> str | None:
        if dep.name not in self._cache:
            self._cache[dep.name] = self._probe(dep)
        return self._cache[dep.name]

    def _probe(self, dep: Dependency) -> str | None:
        target = host_port(dep.url())
        if target is None:
            return f"{dep.label} not configured ({dep.env} unset or invalid)"
        host, port = target
        try:
            socket.create_connection((host, port), timeout=_CONNECT_TIMEOUT_SECONDS).close()
        except OSError:
            return f"{dep.label} not reachable at {host}:{port}"
        return None

    def check(self, item: pytest.Item) -> None:
        for dep in self.dependencies:
            if item.get_closest_marker(f"requires_{dep.name}") is None:
                continue
            problem = self._problem(dep)
            if problem is None:
                continue
            if dep.optional and not dep.url().strip():
                pytest.skip(f"{problem}: opt-in suite")
            if in_ci():
                pytest.fail(f"{problem} (CI=true: infra tests must not be skipped)", pytrace=False)
            pytest.skip(f"{problem}; {_HINT}")
