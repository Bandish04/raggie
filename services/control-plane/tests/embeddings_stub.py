# SPDX-License-Identifier: Apache-2.0

"""Embeddings-gateway /v1/info bodies and a pre-reconciled profile for tests."""

from __future__ import annotations

import time

from raggie_control_plane.config import settings
from raggie_control_plane.embeddings_profile import (
    EmbeddingsInfo,
    EmbeddingsProfile,
    GatewayInfoClient,
)

# The legacy local profile (fingerprint pinned by contracts/embeddings_gateway.schema.json).
LEGACY_INFO = {
    "provider": "local",
    "model": "intfloat/multilingual-e5-large",
    "dim": 1024,
    "fingerprint": "2872ae6a",
    "collection": "raggie_chunks_d1024",
    "sparse_model": "Qdrant/bm25",
    "reranker": {"provider": "local", "model": "jinaai/jina-reranker-v2-base-multilingual"},
    "egress": {"dense_host": None, "rerank_host": None},
}

CLOUD_INFO = {
    "provider": "openai_compatible",
    "model": "text-embedding-3-large",
    "dim": 1024,
    "fingerprint": "5e1f00d2",
    "collection": "raggie_chunks_d1024_5e1f00d2",
    "sparse_model": "Qdrant/bm25",
    "reranker": {"provider": "cohere", "model": "rerank-v3.5"},
    "egress": {"dense_host": "api.openai.com", "rerank_host": "api.cohere.com"},
    "some_future_field": True,  # clients must ignore unknown fields
}


def unknown_profile(**kwargs) -> EmbeddingsProfile:
    """A profile that has never reached the gateway (talks to the `gateway` fixture)."""
    return EmbeddingsProfile(GatewayInfoClient(settings.embeddings_base_url), **kwargs)


def known_profile(info: dict | None = None, **kwargs) -> EmbeddingsProfile:
    """A profile whose gateway profile is known and accepted (no mismatch). The
    client's /info cache is primed, so reading it never touches the network."""
    body = info or LEGACY_INFO
    profile = unknown_profile(**kwargs)
    profile.info = EmbeddingsInfo.model_validate(body)
    profile.stored_fingerprint = body["fingerprint"]
    profile.client._cached = profile.info
    profile.client._fetched_at = time.monotonic()
    return profile
