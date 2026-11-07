#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Offline OpenAI-compatible embeddings upstream for tests (no secrets, stdlib only).

POST /v1/embeddings returns deterministic hashed bag-of-words vectors, so texts
that share words land close together and retrieval still finds the documents.
Used by the kind chaos cluster (scripts/ha) and the cloud leg of
.github/workflows/install-smoke.yml. Not for production.

    python3 scripts/ha/mock_embeddings.py [--port 8080] [--dim 1024]
"""

import argparse
import hashlib
import json
import math
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DIM = int(os.environ.get("DIM", "1024"))


def embed(text):
    v = [0.0] * DIM
    for tok in re.findall(r"\w+", text.lower()):
        h = int.from_bytes(hashlib.blake2b(tok.encode(), digest_size=8).digest(), "big")
        v[h % DIM] += 1.0 if (h >> 32) & 1 else -1.0
    n = math.sqrt(sum(x * x for x in v))
    if n == 0:
        v[0], n = 1.0, 1.0
    return [x / n for x in v]


class Handler(BaseHTTPRequestHandler):
    def _send(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send(200 if self.path == "/healthz" else 404, {"status": "ok"})

    def do_POST(self):
        if not self.path.rstrip("/").endswith("/embeddings"):
            return self._send(404, {"error": "not found"})
        req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
        inputs = req.get("input", [])
        if isinstance(inputs, str):
            inputs = [inputs]
        data = [
            {"object": "embedding", "index": i, "embedding": embed(t)} for i, t in enumerate(inputs)
        ]
        self._send(
            200,
            {
                "object": "list",
                "data": data,
                "model": req.get("model", "mock-embed"),
                "usage": {"prompt_tokens": 0, "total_tokens": 0},
            },
        )

    def log_message(self, *_):
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    parser.add_argument("--dim", type=int, default=DIM)
    args = parser.parse_args()
    DIM = args.dim
    ThreadingHTTPServer(("0.0.0.0", args.port), Handler).serve_forever()
