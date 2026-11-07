# SPDX-License-Identifier: Apache-2.0

"""Cloud dense embeddings via an OpenAI-compatible ``POST {base}/embeddings``.

Works with OpenAI, Jina, Mistral, Voyage and self-hosted TEI / vLLM / Ollama:
the request is ``{"model", "input": [...]}`` plus the configured extra JSON
(``dimensions``, ``input_type``, ``task`` ...), and the response is the OpenAI
shape ``{"data": [{"index", "embedding"}], "usage": {...}}``.

Call behaviour (one shared keep-alive ``httpx.AsyncClient``):
  - query:   short timeout, one retry — the search path must answer fast;
  - passage: long timeout, several retries with full-jitter backoff that honours
    ``Retry-After``; when they run out the caller (ingestion worker) gets
    429 + Retry-After and backs off itself instead of failing the document;
  - 4xx other than 408/429 are never retried (bad key / bad request);
  - inputs are cut to EMBEDDINGS_MAX_INPUT_CHARS and sent in sub-batches of at
    most N inputs / M characters, concurrently, through a slot pool that keeps
    some slots for queries only.
"""

from __future__ import annotations

import asyncio
import email.utils
import math
import random
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Literal
from urllib.parse import urlsplit

import httpx

from raggie_embeddings.config import Settings
from raggie_embeddings.providers.metrics import UPSTREAM_INPUTS, UPSTREAM_REQUESTS, UPSTREAM_TOKENS

InputType = Literal["query", "passage"]
_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}
# A rejected key is the usual cause of these on a hosted API, so the error
# (shown in /readyz and the log) names the setting to check, never its value.
AUTH_FAILURE_STATUS = {401, 403}


class UpstreamError(Exception):
    """An upstream call failed; carries the status the gateway should return."""

    def __init__(self, status_code: int, detail: str, retry_after: int | None = None) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.retry_after = retry_after


class SlotPool:
    """``total`` concurrent upstream slots, ``reserved`` of which only priority
    (query) callers may use. Passages queue on the general slots alone."""

    def __init__(self, total: int, reserved: int) -> None:
        self._general = asyncio.Semaphore(total - reserved)
        self._reserved = asyncio.Semaphore(reserved) if reserved > 0 else None

    @asynccontextmanager
    async def slot(self, *, priority: bool) -> AsyncIterator[None]:
        sem = self._general
        if priority and self._reserved is not None:
            # Prefer a reserved slot, fall back to a free general one, else wait
            # for a reserved slot (which bulk traffic can never hold).
            if not self._reserved.locked() or self._general.locked():
                sem = self._reserved
        async with sem:
            yield


def split_batches(
    texts: list[str], *, max_items: int, max_chars: int
) -> list[list[tuple[int, str]]]:
    """Group (index, text) pairs into batches bounded by item and char counts."""
    batches: list[list[tuple[int, str]]] = []
    current: list[tuple[int, str]] = []
    chars = 0
    for index, text in enumerate(texts):
        if current and (len(current) >= max_items or chars + len(text) > max_chars):
            batches.append(current)
            current, chars = [], 0
        current.append((index, text))
        chars += len(text)
    if current:
        batches.append(current)
    return batches


def parse_retry_after(value: str | None) -> float | None:
    """Seconds from a Retry-After header (delta-seconds or HTTP-date)."""
    if not value:
        return None
    value = value.strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, when.timestamp() - time.time())


def host_of(url: str) -> str | None:
    return urlsplit(url).hostname if url else None


class OpenAICompatDense:
    def __init__(
        self,
        cfg: Settings,
        client: httpx.AsyncClient,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rng: Callable[[], float] = random.random,
    ) -> None:
        self._cfg = cfg
        self._client = client
        self._sleep = sleep
        self._rng = rng
        self._url = f"{cfg.embeddings_upstream_base_url}/embeddings"
        self._slots = SlotPool(
            cfg.embeddings_upstream_concurrency, cfg.embeddings_query_reserved_slots
        )
        self._base_body = dict(cfg.request_extra)
        self._type_extra = {"query": cfg.query_extra, "passage": cfg.passage_extra}
        self._prefix = {"query": cfg.query_prefix, "passage": cfg.passage_prefix}
        self.host = host_of(cfg.embeddings_upstream_base_url)

    async def embed(self, texts: list[str], input_type: InputType) -> list[list[float]]:
        if not texts:
            return []
        limit = self._cfg.embeddings_max_input_chars
        prefix = self._prefix[input_type]
        prepared = [f"{prefix}{text[:limit]}" for text in texts]
        batches = split_batches(
            prepared,
            max_items=self._cfg.embeddings_upstream_batch_size,
            max_chars=self._cfg.embeddings_upstream_batch_max_chars,
        )
        out: list[list[float]] = [[] for _ in prepared]
        try:
            async with asyncio.TaskGroup() as group:
                tasks = [
                    group.create_task(self._embed_batch([t for _, t in batch], input_type))
                    for batch in batches
                ]
        except* UpstreamError as eg:
            raise eg.exceptions[0] from None
        for batch, task in zip(batches, tasks, strict=True):
            for (index, _), vector in zip(batch, task.result(), strict=True):
                out[index] = vector
        return out

    async def _embed_batch(self, inputs: list[str], input_type: InputType) -> list[list[float]]:
        body = {
            "model": self._cfg.embeddings_model,
            **self._base_body,
            **self._type_extra[input_type],
            "input": inputs,
        }
        headers = {}
        if self._cfg.embeddings_upstream_api_key:
            headers["Authorization"] = f"Bearer {self._cfg.embeddings_upstream_api_key}"
        query = input_type == "query"
        timeout = (
            self._cfg.embeddings_query_timeout_seconds
            if query
            else self._cfg.embeddings_passage_timeout_seconds
        )
        retries = (
            self._cfg.embeddings_query_retries if query else self._cfg.embeddings_passage_retries
        )
        # Never sleep longer than this between attempts; a longer Retry-After is
        # handed to the caller instead.
        max_wait = self._cfg.embeddings_retry_backoff_max_seconds
        if query:
            max_wait = min(max_wait, timeout)

        last_status: int | None = None
        last_retry_after: float | None = None
        for attempt in range(retries + 1):
            retry_after: float | None = None
            try:
                async with self._slots.slot(priority=query):
                    response = await self._client.post(
                        self._url, json=body, headers=headers, timeout=timeout
                    )
            except httpx.TimeoutException:
                last_status = 504
            except httpx.TransportError:
                last_status = 503
            else:
                if response.status_code == 200:
                    UPSTREAM_REQUESTS.labels("dense", "ok").inc()
                    UPSTREAM_INPUTS.labels("dense").inc(len(inputs))
                    return self._parse(response, len(inputs))
                if response.status_code not in _RETRYABLE_STATUS:
                    UPSTREAM_REQUESTS.labels("dense", "error").inc()
                    detail = f"embedding upstream rejected the request ({response.status_code})"
                    if response.status_code in AUTH_FAILURE_STATUS:
                        detail += "; check EMBEDDINGS_UPSTREAM_API_KEY in .env.embeddings"
                    raise UpstreamError(502, detail)
                last_status = response.status_code
                retry_after = parse_retry_after(response.headers.get("Retry-After"))
                last_retry_after = retry_after

            if attempt == retries:
                break
            if retry_after is not None:
                if retry_after > max_wait:
                    break  # the upstream wants a longer pause than we hold a request
                delay = retry_after
            else:
                delay = self._rng() * min(
                    max_wait, self._cfg.embeddings_retry_backoff_base_seconds * 2**attempt
                )
            UPSTREAM_REQUESTS.labels("dense", "retry").inc()
            await self._sleep(delay)

        UPSTREAM_REQUESTS.labels("dense", "error").inc()
        if not query or last_status == 429:
            # Passages: tell the worker to come back later rather than fail the doc.
            wait = last_retry_after
            if wait is None:
                wait = self._cfg.embeddings_retry_backoff_max_seconds
            raise UpstreamError(
                429,
                f"embedding upstream unavailable ({last_status}); retry later",
                retry_after=max(1, math.ceil(wait)),
            )
        raise UpstreamError(503, f"embedding upstream unavailable ({last_status})")

    def _parse(self, response: httpx.Response, expected: int) -> list[list[float]]:
        try:
            payload = response.json()
            items = sorted(payload["data"], key=lambda item: item["index"])
            vectors = [[float(x) for x in item["embedding"]] for item in items]
        except (ValueError, KeyError, TypeError) as exc:
            raise UpstreamError(502, "embedding upstream returned an unexpected payload") from exc
        if len(vectors) != expected:
            raise UpstreamError(
                502, f"embedding upstream returned {len(vectors)} embeddings for {expected} inputs"
            )
        dim = self._cfg.embedding_dim
        for vector in vectors:
            if len(vector) != dim:
                raise UpstreamError(
                    502,
                    f"embedding upstream returned {len(vector)}-dimensional vectors; "
                    f"EMBEDDING_DIM={dim}",
                )
        usage = payload.get("usage") or {}
        tokens = usage.get("total_tokens") or usage.get("prompt_tokens")
        if isinstance(tokens, int | float):
            UPSTREAM_TOKENS.inc(tokens)
        return vectors
