# SPDX-License-Identifier: Apache-2.0

"""End-to-end with the real pinned ONNX models (downloads ~2.6 GB once).

Run with EMBEDDINGS_MODEL_TESTS=1; skipped otherwise.
"""

import time

import pytest
from fastapi.testclient import TestClient

from raggie_embeddings.config import Settings
from raggie_embeddings.main import create_app

pytestmark = pytest.mark.model


def _wait_ready(client: TestClient, timeout: float = 120.0) -> None:
    deadline = time.monotonic() + timeout
    while client.get("/readyz").status_code != 200:
        assert time.monotonic() < deadline, client.get("/readyz").json()
        time.sleep(0.2)


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app(Settings(_env_file=None))) as c:
        _wait_ready(c)
        yield c


def test_embeddings_openai_shape_and_dim(client) -> None:
    r = client.post("/v1/embeddings", json={"input": ["merhaba dünya", "hello world"]})
    assert r.status_code == 200
    body = r.json()
    assert body["object"] == "list"
    assert len(body["data"]) == 2
    # intfloat/multilingual-e5-large -> 1024 dims.
    assert len(body["data"][0]["embedding"]) == 1024
    assert body["data"][0]["index"] == 0
    assert body["data"][1]["index"] == 1
    assert body["collection"] == "raggie_chunks_d1024"


def test_embeddings_accepts_single_string(client) -> None:
    r = client.post("/v1/embeddings", json={"input": "tek cümle"})
    assert r.status_code == 200
    assert len(r.json()["data"]) == 1


def test_query_has_sparse_terms(client) -> None:
    body = client.post("/v1/query", json={"query": "yıllık izin politikası"}).json()
    assert len(body["dense"]) == 1024
    assert body["sparse"]["indices"]


def test_real_reranker_prefers_the_relevant_passage(client) -> None:
    docs = [
        "Kantin menüsü her pazartesi güncellenir ve intranet sayfasında yayınlanır.",
        "Çalışanlar yılda 14 gün ücretli yıllık izin hakkına sahiptir; izin talepleri "
        "en az iki hafta önceden yöneticiye iletilmelidir.",
        "Otopark kartları güvenlik ofisinden teslim alınır.",
    ]
    deadline = time.monotonic() + 300
    while True:
        results = client.post(
            "/v1/rerank", json={"query": "Kaç gün yıllık izin hakkım var?", "documents": docs}
        ).json()["results"]
        # Identity order (scores 3,2,1) means the background load is not done yet.
        if [r["score"] for r in results] != [3.0, 2.0, 1.0]:
            break
        assert time.monotonic() < deadline, "reranker never finished loading"
        time.sleep(1)
    assert results[0]["index"] == 1


def test_healthz(client) -> None:
    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 200
