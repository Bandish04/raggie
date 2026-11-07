# SPDX-License-Identifier: Apache-2.0

"""Embedder port + a deterministic mock.

The real adapter (openai_embedder.py) talks to the embeddings gateway; the
ingester depends only on this Protocol, so tests swap in the mock.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@runtime_checkable
class Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


@dataclass
class SparseVec:
    """A sparse vector: parallel arrays of token indices and weights (BM25)."""

    indices: list[int]
    values: list[float]


@runtime_checkable
class SparseEmbedder(Protocol):
    async def embed_sparse(self, texts: list[str]) -> list[SparseVec]: ...


class DeterministicMockEmbedder:
    """Hashes each text to a fixed-dim vector — stable, offline, for tests."""

    def __init__(self, dim: int) -> None:
        self.dim = dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for t in texts:
            digest = hashlib.sha256(t.encode()).digest()
            out.append([digest[i % len(digest)] / 255.0 for i in range(self.dim)])
        return out
