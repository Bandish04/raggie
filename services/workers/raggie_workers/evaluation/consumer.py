# SPDX-License-Identifier: Apache-2.0

"""Auto-evaluator consumer: raggie.chat.completed -> faithfulness score / flag.

Guarantees:
  - idempotent on message_id (re-delivery is a no-op — never double-flag);
  - partial / aborted streams are never scored;
  - throughput sampling above a QPS threshold;
  - judge failures never block the lane and never spuriously flag; a failing
    judge is retried by redelivery up to max_deliveries, then the answer is
    recorded without a faithfulness score;
  - runs on its own LLM quota (separate process + bounded judge concurrency),
    so it cannot starve the chat/retrieval hot path.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from raggie_workers.bus import RedisStreamsBus
from raggie_workers.evaluation.citations import analyze_citations
from raggie_workers.evaluation.dedup import Deduper
from raggie_workers.evaluation.judge import Judge
from raggie_workers.evaluation.sampler import ThroughputSampler
from raggie_workers.evaluation.store import EvalStore
from raggie_workers.topics import CHAT_COMPLETED, EVAL_GROUP

log = logging.getLogger("eval")


@dataclass
class EvalConsumer:
    bus: RedisStreamsBus
    store: EvalStore
    judge: Judge
    deduper: Deduper
    sampler: ThroughputSampler
    score_threshold: float = 0.7
    citation_validity_threshold: float = 1.0
    citation_coverage_threshold: float = 0.6
    max_deliveries: int = 5

    async def handle(self, payload: dict, *, skip_judge: bool = False) -> str:
        """Process one chat.completed event. Returns a status string (for tests
        and logging): duplicate | missing | partial | sampled_out | error |
        unscored | scored | flagged. skip_judge records the citation checks
        without a faithfulness score (the judge has failed too often)."""
        message_id = str(payload.get("message_id", ""))
        if not message_id:
            return "missing"
        token = await self.deduper.claim(message_id)
        if token is None:
            return "duplicate"

        msg = await self.store.load_bot_message(message_id)
        if msg is None:
            await self.deduper.complete(message_id, token)
            return "missing"
        if msg["partial"]:
            await self.deduper.complete(message_id, token)
            return "partial"  # aborted streams are never scored
        if not self.sampler.should(time.monotonic()):
            await self.deduper.complete(message_id, token)
            return "sampled_out"

        citations = analyze_citations(msg["content"], msg["source_count"])
        score: float | None = None
        if not skip_judge:
            try:
                score = await self.judge.score(msg["content"], msg["context"])
            except Exception:  # noqa: BLE001 — a judge failure must never flag or crash the lane
                log.exception("eval judge failed for message %s", message_id)
                await self.deduper.release(message_id, token)
                return "error"

        available_scores = [
            value
            for value in (score, citations.validity_score, citations.coverage_score)
            if value is not None
        ]
        if not available_scores:
            await self.deduper.complete(message_id, token)
            return "unscored"

        flagged = (
            (score is not None and score < self.score_threshold)
            or (
                citations.validity_score is not None
                and citations.validity_score < self.citation_validity_threshold
            )
            or (
                citations.coverage_score is not None
                and citations.coverage_score < self.citation_coverage_threshold
            )
        )
        overall_score = min(available_scores)
        await self.store.record(
            message_id,
            msg["conversation_id"],
            overall_score=overall_score,
            faithfulness_score=score,
            citation_validity_score=citations.validity_score,
            citation_coverage_score=citations.coverage_score,
            flagged=flagged,
            details={
                "faithfulness_score": score,
                "citation": citations.as_dict(),
                "thresholds": {
                    "faithfulness": self.score_threshold,
                    "citation_validity": self.citation_validity_threshold,
                    "citation_coverage": self.citation_coverage_threshold,
                },
            },
        )
        await self.deduper.complete(message_id, token)
        log.info(
            "evaluated message %s score=%.3f faithfulness=%s citation_validity=%s"
            " citation_coverage=%s flagged=%s",
            message_id,
            overall_score,
            score,
            citations.validity_score,
            citations.coverage_score,
            flagged,
        )
        return "flagged" if flagged else "scored"

    async def run_once(self, consumer_name: str = "eval-1") -> int:
        await self.bus.ensure_group(CHAT_COMPLETED, EVAL_GROUP)
        msgs = await self.bus.consume(CHAT_COMPLETED, EVAL_GROUP, consumer_name)
        for msg_id, payload in msgs:
            status = "error"
            try:
                status = await self.handle(payload)
                if status == "error":
                    status = await self._give_up_at_cap(msg_id, payload)
            except Exception:  # noqa: BLE001 — never let one event kill the loop
                log.exception("eval handler crashed")
            if status != "error":
                await self.bus.ack(CHAT_COMPLETED, EVAL_GROUP, msg_id)
        return len(msgs)

    async def _give_up_at_cap(self, msg_id: str, payload: dict) -> str:
        """After a judge failure: keep the event pending for redelivery until it
        has been delivered max_deliveries times, then record it unscored so it
        stops cycling through a judge that keeps failing."""
        deliveries = await self.bus.delivery_count(CHAT_COMPLETED, EVAL_GROUP, msg_id)
        if deliveries < self.max_deliveries:
            return "error"
        log.warning(
            "eval judge failed on %d deliveries of message %s; recording it without"
            " a faithfulness score (EVAL_MAX_DELIVERIES=%d)",
            deliveries,
            payload.get("message_id"),
            self.max_deliveries,
        )
        return await self.handle(payload, skip_judge=True)
