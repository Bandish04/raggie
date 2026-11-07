# SPDX-License-Identifier: Apache-2.0

"""Local fastembed (ONNX, CPU) providers: dense, BM25 sparse and cross-encoder.

Inference is synchronous, so every call runs in a worker thread to keep the
event loop free for health checks and concurrent requests.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from raggie_embeddings.config import Settings
from raggie_embeddings.providers.models import (
    ensure_model,
    hf_offline,
    register_custom_rerankers,
)
from raggie_embeddings.providers.openai_compat import InputType

logger = logging.getLogger("raggie.embeddings.local")


def _model_kwargs(model_name: str, cfg: Settings) -> dict[str, Any]:
    path = ensure_model(model_name, cfg.model_cache_dir)
    kwargs: dict[str, Any] = {"model_name": model_name, "cache_dir": cfg.model_cache_dir}
    if path is not None:
        kwargs["specific_model_path"] = path  # baked snapshot, read in place
    elif hf_offline():
        # Unpinned model under HF_HUB_OFFLINE: use fastembed's cache only, never
        # attempt a download (read-only root filesystem).
        kwargs["local_files_only"] = True
    if cfg.embeddings_onnx_threads is not None:
        kwargs["threads"] = cfg.embeddings_onnx_threads
    return kwargs


class LocalDense:
    host: str | None = None  # no egress

    def __init__(self, cfg: Settings, model: Any) -> None:
        self._cfg = cfg
        self._model = model
        self._prefix = {"query": cfg.query_prefix, "passage": cfg.passage_prefix}

    @classmethod
    def load(cls, cfg: Settings) -> LocalDense:
        from fastembed import TextEmbedding

        return cls(cfg, TextEmbedding(**_model_kwargs(cfg.embeddings_model, cfg)))

    def _embed_sync(self, texts: list[str], input_type: InputType) -> list[list[float]]:
        limit = self._cfg.embeddings_max_input_chars
        prefix = self._prefix[input_type]
        prepared = [f"{prefix}{text[:limit]}" for text in texts]
        return [vector.tolist() for vector in self._model.embed(prepared)]

    async def embed(self, texts: list[str], input_type: InputType) -> list[list[float]]:
        if not texts:
            return []
        return await asyncio.to_thread(self._embed_sync, texts, input_type)


_EMPTY_SPARSE: dict[str, list] = {"indices": [], "values": []}


class LocalSparse:
    """BM25 term weights. ``model=None`` (disabled / failed to load) returns
    empty vectors so callers index and search dense-only."""

    def __init__(self, model: Any | None) -> None:
        self._model = model

    @classmethod
    def load(cls, cfg: Settings) -> LocalSparse:
        if not cfg.sparse_enabled:
            return cls(None)
        try:
            from fastembed import SparseTextEmbedding

            kwargs = _model_kwargs(cfg.sparse_model, cfg)
            if cfg.sparse_language:
                kwargs["language"] = cfg.sparse_language
            return cls(SparseTextEmbedding(**kwargs))
        except Exception:
            logger.exception("sparse model load failed (%s); sparse disabled", cfg.sparse_model)
            return cls(None)

    @property
    def available(self) -> bool:
        return self._model is not None

    def _documents_sync(self, texts: list[str]) -> list[dict]:
        if self._model is None:
            return [dict(_EMPTY_SPARSE) for _ in texts]
        return [
            {"indices": emb.indices.tolist(), "values": emb.values.tolist()}
            for emb in self._model.embed(texts)  # document mode -> term frequencies
        ]

    def _query_sync(self, query: str) -> dict:
        if self._model is None:
            return dict(_EMPTY_SPARSE)
        emb = next(iter(self._model.query_embed(query)))  # query mode -> constant weights
        return {"indices": emb.indices.tolist(), "values": emb.values.tolist()}

    async def embed_documents(self, texts: list[str]) -> list[dict]:
        return await asyncio.to_thread(self._documents_sync, texts)

    async def embed_query(self, query: str) -> dict:
        return await asyncio.to_thread(self._query_sync, query)


class RerankerNotReady(Exception):
    """The local cross-encoder is still loading or failed to load."""


class LocalReranker:
    host: str | None = None  # no egress

    def __init__(self, cfg: Settings, model: Any | None = None) -> None:
        self._cfg = cfg
        self._model = model
        self.model = cfg.reranker_model

    @staticmethod
    def load_model(cfg: Settings) -> Any:
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        register_custom_rerankers()
        return TextCrossEncoder(**_model_kwargs(cfg.reranker_model, cfg))

    async def load_in_background(self) -> None:
        """Never raises: until (unless) this finishes, rerank falls back to the
        identity order and the edge keeps the fused ranking."""
        try:
            logger.info("loading reranker model %s", self._cfg.reranker_model)
            self._model = await asyncio.to_thread(self.load_model, self._cfg)
            logger.info("reranker model ready")
        except Exception:
            logger.exception(
                "reranker load failed (%s); reranking disabled, fused order kept",
                self._cfg.reranker_model,
            )

    async def rerank(self, query: str, documents: list[str]) -> list[float]:
        model = self._model
        if model is None:
            raise RerankerNotReady(self._cfg.reranker_model)
        limit = self._cfg.reranker_max_doc_chars
        docs = [doc[:limit] for doc in documents]
        batch_size = self._cfg.reranker_batch_size
        return await asyncio.to_thread(
            lambda: [float(s) for s in model.rerank(query, docs, batch_size=batch_size)]
        )
