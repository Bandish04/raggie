# SPDX-License-Identifier: Apache-2.0

"""Cloud rerankers, three wire dialects:

  cohere (also Jina and vLLM ``/rerank``):
      {model, query, documents, top_n}  ->  {"results": [{index, relevance_score}]}
  voyage:
      {model, query, documents, top_k}  ->  {"data": [{index, relevance_score}]}
  tei (Hugging Face text-embeddings-inference ``/rerank``):
      {query, texts, truncate}          ->  [{index, score}]

One attempt with a short timeout and no retry: the edge already fails open to
the fused order, so a slow reranker must never hold up an answer. Score scales
differ per provider; callers only rely on the ordering.
"""

from __future__ import annotations

from typing import Any

import httpx

from raggie_embeddings.config import Settings
from raggie_embeddings.providers.metrics import UPSTREAM_INPUTS, UPSTREAM_REQUESTS
from raggie_embeddings.providers.openai_compat import AUTH_FAILURE_STATUS, host_of


class RerankError(Exception):
    """The remote reranker failed; the gateway falls back to identity order."""


class RemoteReranker:
    def __init__(self, cfg: Settings, client: httpx.AsyncClient) -> None:
        self._cfg = cfg
        self._client = client
        self.dialect = cfg.reranker_provider
        self.model = cfg.reranker_model
        self.host = host_of(cfg.reranker_upstream_url)

    def _body(self, query: str, documents: list[str]) -> dict[str, Any]:
        if self.dialect == "tei":
            return {"query": query, "texts": documents, "truncate": True}
        limit_key = "top_k" if self.dialect == "voyage" else "top_n"
        return {
            "model": self.model,
            "query": query,
            "documents": documents,
            limit_key: len(documents),
        }

    def _items(self, payload: Any) -> list[tuple[int, float]]:
        if self.dialect == "tei":
            rows, score_key = payload, "score"
        elif self.dialect == "voyage":
            rows, score_key = payload["data"], "relevance_score"
        else:
            rows, score_key = payload["results"], "relevance_score"
        return [(int(row["index"]), float(row[score_key])) for row in rows]

    async def rerank(self, query: str, documents: list[str]) -> list[float]:
        """Relevance score per input document (same order as ``documents``)."""
        limit = self._cfg.reranker_max_doc_chars
        docs = [doc[:limit] for doc in documents]
        headers = {}
        if self._cfg.reranker_upstream_api_key:
            headers["Authorization"] = f"Bearer {self._cfg.reranker_upstream_api_key}"
        try:
            response = await self._client.post(
                self._cfg.reranker_upstream_url,
                json=self._body(query, docs),
                headers=headers,
                timeout=self._cfg.reranker_timeout_seconds,
            )
        except httpx.HTTPError as exc:
            UPSTREAM_REQUESTS.labels("rerank", "error").inc()
            raise RerankError(f"rerank upstream unreachable: {type(exc).__name__}") from exc
        if response.status_code != 200:
            UPSTREAM_REQUESTS.labels("rerank", "error").inc()
            detail = f"rerank upstream returned {response.status_code}"
            if response.status_code in AUTH_FAILURE_STATUS:
                detail += "; check RERANKER_UPSTREAM_API_KEY in .env.embeddings"
            raise RerankError(detail)
        try:
            items = self._items(response.json())
        except (ValueError, KeyError, TypeError) as exc:
            UPSTREAM_REQUESTS.labels("rerank", "error").inc()
            raise RerankError("rerank upstream returned an unexpected payload") from exc
        UPSTREAM_REQUESTS.labels("rerank", "ok").inc()
        UPSTREAM_INPUTS.labels("rerank").inc(len(docs))

        scores: dict[int, float] = {i: s for i, s in items if 0 <= i < len(docs)}
        floor = min(scores.values(), default=0.0) - 1.0
        # Documents the upstream did not score rank after every scored one, in
        # their original order.
        return [scores.get(i, floor - i * 1e-6) for i in range(len(docs))]
