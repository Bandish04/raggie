# SPDX-License-Identifier: Apache-2.0

"""Stand-ins for fastembed models and app builders (no ONNX downloads in tests)."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

import httpx
import numpy as np
from fastapi.testclient import TestClient

from raggie_embeddings.config import Settings
from raggie_embeddings.main import create_app
from raggie_embeddings.providers.local import LocalDense, LocalReranker, LocalSparse


class FakeDenseModel:
    def __init__(self, dim: int) -> None:
        self.dim = dim
        self.calls: list[list[str]] = []

    def embed(self, texts):
        self.calls.append(list(texts))
        for text in texts:
            yield np.full(self.dim, float(len(text)), dtype=np.float32)


@dataclass
class _Sparse:
    indices: np.ndarray
    values: np.ndarray


class FakeSparseModel:
    def embed(self, texts):
        for text in texts:
            yield _Sparse(np.array([len(text) % 97, 101]), np.array([1.0, 0.5]))

    def query_embed(self, query):
        yield _Sparse(np.array([7]), np.array([1.0]))


class FakeCrossEncoder:
    def rerank(self, query, documents, batch_size=64):
        # Longer documents win: deterministic and order-revealing.
        return [float(len(doc)) for doc in documents]


def local_stub_app(cfg: Settings, *, dim: int | None = None, redis=None, dense_model=None):
    dense_model = dense_model or FakeDenseModel(dim or cfg.embedding_dim)
    return create_app(
        cfg,
        dense=LocalDense(cfg, dense_model),
        sparse=LocalSparse(FakeSparseModel()),
        reranker=LocalReranker(cfg, FakeCrossEncoder()),
        redis=redis,
    )


def cloud_mock_app(cfg: Settings, *, redis=None):
    return create_app(
        cfg, sparse=LocalSparse(FakeSparseModel()), redis=redis, http_client=httpx.AsyncClient()
    )


def openai_upstream(request: httpx.Request, *, dim: int) -> httpx.Response:
    inputs = json.loads(request.content)["input"]
    return httpx.Response(
        200,
        json={
            "object": "list",
            "data": [
                {"object": "embedding", "index": i, "embedding": [0.1 * (i + 1)] * dim}
                for i in range(len(inputs))
            ],
            "usage": {"prompt_tokens": len(inputs), "total_tokens": len(inputs)},
        },
    )


def wait_ready(client: TestClient, timeout: float = 5.0) -> httpx.Response:
    deadline = time.monotonic() + timeout
    response = client.get("/readyz")
    while response.status_code != 200 and time.monotonic() < deadline:
        time.sleep(0.02)
        response = client.get("/readyz")
    return response


def wait_probe_failed(client: TestClient, timeout: float = 5.0) -> httpx.Response:
    deadline = time.monotonic() + timeout
    response = client.get("/readyz")
    while response.json().get("status") == "loading" and time.monotonic() < deadline:
        time.sleep(0.02)
        response = client.get("/readyz")
    return response
