# SPDX-License-Identifier: Apache-2.0

"""Prometheus counters for upstream egress (cost/abuse visibility) and the cache."""

from __future__ import annotations

from prometheus_client import Counter

UPSTREAM_REQUESTS = Counter(
    "raggie_embeddings_upstream_requests_total",
    "Requests sent to a cloud upstream.",
    ["kind", "outcome"],  # kind: dense|rerank; outcome: ok|retry|error
)
UPSTREAM_TOKENS = Counter(
    "raggie_embeddings_upstream_tokens_total",
    "Tokens billed by the dense upstream (from its usage block).",
)
UPSTREAM_INPUTS = Counter(
    "raggie_embeddings_upstream_inputs_total",
    "Texts sent to a cloud upstream.",
    ["kind"],
)
QUERY_CACHE = Counter(
    "raggie_embeddings_query_cache_total",
    "Query-embedding cache lookups.",
    ["result"],  # hit|miss|error
)
