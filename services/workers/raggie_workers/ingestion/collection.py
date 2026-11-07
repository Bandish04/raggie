# SPDX-License-Identifier: Apache-2.0

"""Qdrant collection naming.

A Qdrant collection has a fixed vector size, and Raggie supports per-workspace
embedding dimensions, so chunks are stored in a collection keyed by dimension
(``raggie_chunks_d{dim}``) with ``workspace_id`` in the payload for tenant
filtering. The derivation is the single source of truth in
``contracts/qdrant_collection.json``; the Go edge implements the same rule and
CI checks both against that fixture. This name is the fallback for legacy
events: newer events carry the gateway-chosen ``collection`` explicitly.
"""

from __future__ import annotations

# Every Raggie chunk collection starts with this (legacy raggie_chunks_d{dim} and
# gateway profiles raggie_chunks_d{dim}_{fingerprint}); the deletion cascade
# purges a document from all of them.
COLLECTION_PREFIX = "raggie_chunks_"


def collection_name(embedding_dim: int) -> str:
    if embedding_dim <= 0:
        raise ValueError("embedding_dim must be positive")
    return f"raggie_chunks_d{embedding_dim}"
