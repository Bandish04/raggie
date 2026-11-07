# SPDX-License-Identifier: Apache-2.0

"""A tiny stdlib HTTP server exposing /healthz, /readyz, /metrics for a worker.

Workers are not request servers, but k8s still needs liveness/readiness probes
and Prometheus needs a scrape target — so each worker runs this in a daemon
thread alongside its async consume loop.
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from prometheus_client import CONTENT_TYPE_LATEST, generate_latest


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 (stdlib signature)
        if self.path in ("/healthz", "/readyz"):
            self._respond(200, b'{"status":"ok"}', "application/json")
        elif self.path == "/metrics":
            self._respond(200, generate_latest(), CONTENT_TYPE_LATEST)
        else:
            self._respond(404, b'{"error":"not found"}', "application/json")

    def _respond(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:
        # Silence default stderr access logging; structured logs handle this.
        return


def start_health_server(port: int) -> ThreadingHTTPServer:
    """Start the health server in a daemon thread. Pass port=0 for an ephemeral port."""
    # Container health endpoint: must listen on all interfaces for the kubelet /
    # compose probes; it serves only static liveness/readiness JSON.
    server = ThreadingHTTPServer(("0.0.0.0", port), _Handler)  # nosec B104
    thread = threading.Thread(target=server.serve_forever, daemon=True, name="health-server")
    thread.start()
    return server
