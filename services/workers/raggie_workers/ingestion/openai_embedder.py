# SPDX-License-Identifier: Apache-2.0

"""Clients for the embeddings gateway (services/embeddings).

Dense: POST {base_url}/embeddings with ``input_type: "passage"`` (the gateway
selects prefixes / provider extras by it). The response carries the gateway's
active profile ``fingerprint`` and ``collection``
(contracts/embeddings_gateway.schema.json); a fingerprint different from the
one a document is being indexed for is a terminal FingerprintMismatch.

Retries: 429 honours the gateway's Retry-After (it returns 429 once its own
upstream retries are exhausted), 5xx/transport errors back off exponentially,
other 4xx (bad auth / bad request) fail immediately. Auth: ``Authorization:
Bearer $INTERNAL_API_SECRET`` when a secret is configured (the gateway enforces
it in cloud mode).
"""

from __future__ import annotations

import asyncio
import email.utils
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx

from raggie_workers.ingestion.embedder import SparseVec

_BACKOFF_BASE_SECONDS = 0.5
_BACKOFF_MAX_SECONDS = 30.0
# Never park a worker slot longer than this on one Retry-After.
_RETRY_AFTER_MAX_SECONDS = 300.0


class FingerprintMismatch(RuntimeError):
    """The gateway embeds with a different profile than the document's.

    Terminal: retrying cannot help; the document must be re-embedded under the
    new profile (control-plane re-embed flow)."""

    def __init__(self, expected: str, actual: str, *, mid_document: bool = False) -> None:
        if mid_document:
            message = (
                f"gateway embedding profile changed mid-document "
                f"({expected} -> {actual}); re-embed required"
            )
        else:
            message = (
                f"document is indexed with embedding profile {expected} but the "
                f"gateway now embeds with {actual}; re-embed required"
            )
        super().__init__(message)
        self.expected = expected
        self.actual = actual
        self.mid_document = mid_document

    def __reduce__(self):
        return (type(self), (self.expected, self.actual), {"mid_document": self.mid_document})

    def __setstate__(self, state: dict) -> None:
        self.__dict__.update(state)


@dataclass
class EmbedResult:
    vectors: list[list[float]]
    fingerprint: str | None
    collection: str | None


def _retry_after_seconds(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            seconds = email.utils.parsedate_to_datetime(value).timestamp() - time.time()
        except (TypeError, ValueError):
            return None
    return min(max(0.0, seconds), _RETRY_AFTER_MAX_SECONDS)


class _GatewayClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        client: httpx.AsyncClient | None,
        max_retries: int,
        timeout: float,
        sleep: Callable[[float], Awaitable[None]],
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self._max_retries = max_retries
        self._sleep = sleep

    async def _post(self, path: str, payload: dict) -> dict:
        for attempt in range(self._max_retries + 1):
            try:
                resp = await self._client.post(
                    f"{self._base_url}{path}", json=payload, headers=self._headers
                )
            except httpx.TransportError:
                if attempt == self._max_retries:
                    raise
                await self._sleep(min(_BACKOFF_BASE_SECONDS * 2**attempt, _BACKOFF_MAX_SECONDS))
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == self._max_retries:
                    resp.raise_for_status()
                delay = _retry_after_seconds(resp) if resp.status_code == 429 else None
                if delay is None:
                    delay = min(_BACKOFF_BASE_SECONDS * 2**attempt, _BACKOFF_MAX_SECONDS)
                await self._sleep(delay)
                continue
            resp.raise_for_status()  # other 4xx: not retryable
            return resp.json()
        raise AssertionError("unreachable")  # pragma: no cover

    async def aclose(self) -> None:
        await self._client.aclose()


class OpenAICompatibleEmbedder(_GatewayClient):
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str = "",
        model: str | None = None,
        client: httpx.AsyncClient | None = None,
        max_retries: int = 6,
        timeout: float = 180.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        super().__init__(
            base_url=base_url,
            api_key=api_key,
            client=client,
            max_retries=max_retries,
            timeout=timeout,
            sleep=sleep,
        )
        self._model = model

    async def embed_with_profile(
        self, texts: list[str], *, expected_fingerprint: str | None = None
    ) -> EmbedResult:
        if not texts:
            return EmbedResult([], None, None)
        payload: dict = {"input": texts, "input_type": "passage"}
        if self._model:
            payload["model"] = self._model
        data = await self._post("/embeddings", payload)
        # OpenAI shape: {"data": [{"index": i, "embedding": [...]}, ...]}
        items = sorted(data["data"], key=lambda d: d["index"])
        fingerprint = data.get("fingerprint")
        if expected_fingerprint and fingerprint and fingerprint != expected_fingerprint:
            raise FingerprintMismatch(expected_fingerprint, fingerprint)
        return EmbedResult(
            vectors=[item["embedding"] for item in items],
            fingerprint=fingerprint,
            collection=data.get("collection"),
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return (await self.embed_with_profile(texts)).vectors


class OpenAICompatibleSparseEmbedder(_GatewayClient):
    """Sparse (BM25) vectors from POST {base_url}/sparse on the gateway (always
    computed locally there). Same auth and retry discipline as the dense client.
    Response: {"data": [{"index": i, "indices": [...], "values": [...]}, ...]}."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str = "",
        client: httpx.AsyncClient | None = None,
        max_retries: int = 6,
        timeout: float = 180.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        super().__init__(
            base_url=base_url,
            api_key=api_key,
            client=client,
            max_retries=max_retries,
            timeout=timeout,
            sleep=sleep,
        )

    async def embed_sparse(self, texts: list[str]) -> list[SparseVec]:
        if not texts:
            return []
        data = await self._post("/sparse", {"input": texts})
        items = sorted(data["data"], key=lambda d: d["index"])
        return [
            SparseVec(indices=list(item["indices"]), values=list(item["values"])) for item in items
        ]
