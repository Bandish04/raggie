# SPDX-License-Identifier: Apache-2.0

"""Faithfulness judge — scores how well an answer is supported by its context.

Calls the OpenAI-compatible chat-completions endpoint (LLMAAS_BASE_URL) with a strict
scoring prompt. Runs in the eval worker process, isolated from the edge's chat
pool; a bounded semaphore caps concurrent judge calls so the eval lane never
overwhelms the shared upstream."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Protocol

import httpx

log = logging.getLogger("eval")

# Matches a 0.0–1.0 style score anywhere in the reply (clamped after parsing).
_NUM = re.compile(r"\b[01](?:\.\d+)?\b|\b0?\.\d+\b")

_SYSTEM = (
    "You are a strict faithfulness evaluator for a retrieval-augmented assistant. "
    "Given CONTEXT and an ANSWER, rate how well the ANSWER is supported by the "
    "CONTEXT, from 0.0 (unsupported or hallucinated) to 1.0 (fully supported). "
    "Reply with ONLY the number."
)


class Judge(Protocol):
    async def score(self, answer: str, context: str) -> float | None:
        """Return a faithfulness score in [0, 1], or None if it can't be scored."""
        ...


class FaithfulnessJudge:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        max_concurrency: int = 4,
        max_tokens: int = 2000,
        timeout: float = 30.0,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._key = api_key
        self._model = model
        self._max_tokens = max_tokens
        self._timeout = timeout
        # The eval-pool quota: never more than N concurrent judge calls upstream.
        self._sem = asyncio.Semaphore(max_concurrency)

    async def score(self, answer: str, context: str) -> float | None:
        if not answer.strip() or not context.strip():
            return None
        body = {
            "model": self._model,
            "temperature": 0,
            "max_tokens": self._max_tokens,
            "messages": [
                {"role": "system", "content": _SYSTEM},
                {
                    "role": "user",
                    "content": f"CONTEXT:\n{context}\n\nANSWER:\n{answer}\n\nScore:",
                },
            ],
        }
        async with self._sem:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                try:
                    # httpx timeouts are per phase, so an upstream that trickles
                    # bytes never trips them; this caps the whole call.
                    async with asyncio.timeout(self._timeout):
                        resp = await client.post(
                            f"{self._base}/chat/completions",
                            json=body,
                            headers={"Authorization": f"Bearer {self._key}"},
                        )
                except (httpx.ReadTimeout, TimeoutError):
                    # The model is reachable but too slow for the budget. Retrying
                    # would re-send the same prompt to the same model, so leave the
                    # answer unscored instead of redelivering it forever.
                    log.warning(
                        "eval judge timed out after %.0fs; answer left unscored"
                        " (raise EVAL_LLM_TIMEOUT_SECONDS for slow models)",
                        self._timeout,
                    )
                    return None
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"].get("content", "")
        return parse_score(content)


def parse_score(text: str) -> float | None:
    """Extract the first 0–1 number from the model's reply, clamped to [0, 1]."""
    match = _NUM.search(text or "")
    if match is None:
        return None
    try:
        return max(0.0, min(1.0, float(match.group())))
    except ValueError:
        return None
