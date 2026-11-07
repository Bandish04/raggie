# SPDX-License-Identifier: Apache-2.0

"""The locked qdrant-client stays within one minor of the pinned Qdrant server
and still exposes every call and model the vector store uses (no server needed)."""

from __future__ import annotations

import inspect
from importlib.metadata import version

import pytest
from qdrant_client import AsyncQdrantClient, models

# Qdrant server image pinned in compose/k8s/helm; clients should be within 1 minor.
QDRANT_SERVER = (1, 20)


def test_client_within_one_minor_of_server() -> None:
    major, minor = (int(part) for part in version("qdrant-client").split(".")[:2])
    assert major == QDRANT_SERVER[0]
    assert abs(minor - QDRANT_SERVER[1]) <= 1, version("qdrant-client")


@pytest.mark.parametrize(
    ("method", "params"),
    [
        ("collection_exists", {"collection_name"}),
        (
            "create_collection",
            {
                "collection_name",
                "vectors_config",
                "sparse_vectors_config",
                "shard_number",
                "replication_factor",
                "write_consistency_factor",
            },
        ),
        ("create_payload_index", {"collection_name", "field_name", "field_schema"}),
        ("upsert", {"collection_name", "points"}),
        ("delete", {"collection_name", "points_selector"}),
        (
            "query_points",
            {"collection_name", "query", "using", "query_filter", "limit", "with_payload"},
        ),
    ],
)
def test_async_client_calls_we_use(method, params) -> None:
    fn = getattr(AsyncQdrantClient, method)
    assert params <= set(inspect.signature(fn).parameters), method


def test_models_we_use() -> None:
    models.VectorParams(
        size=4,
        distance=models.Distance.COSINE,
        hnsw_config=models.HnswConfigDiff(m=32, ef_construct=256),
    )
    models.SparseVectorParams(modifier=models.Modifier.IDF)
    models.PointStruct(
        id=1, vector={"dense": [0.0] * 4, "bm25": models.SparseVector(indices=[1], values=[1.0])}
    )
    models.FilterSelector(
        filter=models.Filter(
            must=[
                models.FieldCondition(key="document_id", match=models.MatchValue(value="d")),
                models.FieldCondition(key="chunk_index", range=models.Range(gte=3)),
            ]
        )
    )
    assert models.PayloadSchemaType.KEYWORD
    from qdrant_client.http.exceptions import (  # noqa: F401
        ResponseHandlingException,
        UnexpectedResponse,
    )
