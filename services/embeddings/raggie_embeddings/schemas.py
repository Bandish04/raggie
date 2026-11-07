# SPDX-License-Identifier: Apache-2.0

"""Request/response models of the gateway (mirrors
contracts/embeddings_gateway.schema.json; tests keep the two in sync)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class EmbeddingsRequest(BaseModel):
    input: str | list[str]
    model: str | None = None  # accepted for OpenAI compatibility; ignored
    # "query" | "passage"; anything else is treated as passage (backward compatible).
    input_type: str = "passage"


class EmbeddingItem(BaseModel):
    object: Literal["embedding"] = "embedding"
    index: int
    embedding: list[float]


class Usage(BaseModel):
    prompt_tokens: int
    total_tokens: int


class EmbeddingsResponse(BaseModel):
    object: Literal["list"] = "list"
    data: list[EmbeddingItem]
    model: str
    usage: Usage
    collection: str
    fingerprint: str


class SparseRequest(BaseModel):
    input: str | list[str]


class SparseVector(BaseModel):
    indices: list[int]
    values: list[float]


class SparseItem(SparseVector):
    index: int


class SparseResponse(BaseModel):
    data: list[SparseItem]


class QueryRequest(BaseModel):
    query: str


class QueryResponse(BaseModel):
    dense: list[float]
    sparse: SparseVector
    collection: str
    fingerprint: str


class RerankRequest(BaseModel):
    query: str
    documents: list[str]
    top_n: int | None = Field(default=None, ge=1)


class RerankResult(BaseModel):
    index: int
    score: float


class RerankResponse(BaseModel):
    results: list[RerankResult]


class RerankerInfo(BaseModel):
    provider: Literal["local", "cohere", "voyage", "tei", "none"]
    model: str | None


class EgressInfo(BaseModel):
    dense_host: str | None
    rerank_host: str | None


class InfoResponse(BaseModel):
    provider: Literal["local", "openai_compatible"]
    model: str
    dim: int
    fingerprint: str
    collection: str
    sparse_model: str | None
    reranker: RerankerInfo
    egress: EgressInfo


class ErrorResponse(BaseModel):
    detail: str
