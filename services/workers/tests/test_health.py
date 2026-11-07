# SPDX-License-Identifier: Apache-2.0

import urllib.request

from raggie_workers.health import start_health_server


def test_healthz_returns_200() -> None:
    server = start_health_server(0)
    port = server.server_address[1]
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2) as r:
            assert r.status == 200
    finally:
        server.shutdown()


def test_metrics_returns_200() -> None:
    server = start_health_server(0)
    port = server.server_address[1]
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics", timeout=2) as r:
            assert r.status == 200
    finally:
        server.shutdown()
