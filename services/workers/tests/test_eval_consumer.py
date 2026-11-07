# SPDX-License-Identifier: Apache-2.0

import pytest

from raggie_workers.evaluation.consumer import EvalConsumer
from raggie_workers.evaluation.dedup import InMemoryDeduper
from raggie_workers.evaluation.sampler import ThroughputSampler

pytestmark = pytest.mark.asyncio


def _msg(partial=False, *, content="Paris is the capital of France [1].", source_count=1):
    return {
        "content": content,
        "context": "France's capital is Paris.",
        "source_count": source_count,
        "partial": partial,
        "conversation_id": "11111111-1111-1111-1111-111111111111",
    }


class FakeStore:
    def __init__(self, msg):
        self.msg = msg
        self.recorded = []

    async def load_bot_message(self, message_id):
        return self.msg

    async def record(self, message_id, conversation_id, **result):
        self.recorded.append((message_id, conversation_id, result))


class FakeJudge:
    def __init__(self, score=None, raises=False):
        self.score_val = score
        self.raises = raises
        self.calls = 0

    async def score(self, answer, context):
        self.calls += 1
        if self.raises:
            raise RuntimeError("upstream boom")
        return self.score_val


def _consumer(store, judge, threshold=0.7, deduper=None):
    return EvalConsumer(
        bus=None,
        store=store,
        judge=judge,
        deduper=deduper or InMemoryDeduper(),
        sampler=ThroughputSampler(qps_threshold=10_000),  # never sample in tests
        score_threshold=threshold,
    )


async def test_high_score_is_recorded_not_flagged():
    store, judge = FakeStore(_msg()), FakeJudge(score=0.92)
    status = await _consumer(store, judge).handle({"message_id": "m1"})
    assert status == "scored"
    message_id, conversation_id, result = store.recorded[0]
    assert message_id == "m1"
    assert conversation_id == "11111111-1111-1111-1111-111111111111"
    assert result["overall_score"] == 0.92
    assert result["citation_validity_score"] == 1.0
    assert result["citation_coverage_score"] == 1.0
    assert result["flagged"] is False


async def test_low_score_flags():
    store, judge = FakeStore(_msg()), FakeJudge(score=0.4)
    status = await _consumer(store, judge).handle({"message_id": "m2"})
    assert status == "flagged"
    assert store.recorded[0][2]["flagged"] is True


async def test_duplicate_is_noop():
    store, judge = FakeStore(_msg()), FakeJudge(score=0.4)
    c = _consumer(store, judge)
    assert await c.handle({"message_id": "dup"}) == "flagged"
    assert await c.handle({"message_id": "dup"}) == "duplicate"
    assert len(store.recorded) == 1  # never double-flagged
    assert judge.calls == 1


async def test_partial_stream_not_scored():
    store, judge = FakeStore(_msg(partial=True)), FakeJudge(score=0.1)
    status = await _consumer(store, judge).handle({"message_id": "m3"})
    assert status == "partial"
    assert store.recorded == []
    assert judge.calls == 0


async def test_judge_failure_does_not_flag():
    store, judge = FakeStore(_msg()), FakeJudge(raises=True)
    consumer = _consumer(store, judge)
    status = await consumer.handle({"message_id": "m4"})
    assert status == "error"
    assert store.recorded == []
    judge.raises = False
    judge.score_val = 0.9
    assert await consumer.handle({"message_id": "m4"}) == "scored"


async def test_missing_message_is_noop():
    store, judge = FakeStore(None), FakeJudge(score=0.9)
    status = await _consumer(store, judge).handle({"message_id": "gone"})
    assert status == "missing"
    assert store.recorded == []


async def test_unscored_when_judge_returns_none():
    store, judge = FakeStore(_msg(content="Merhaba.", source_count=0)), FakeJudge(score=None)
    status = await _consumer(store, judge).handle({"message_id": "m5"})
    assert status == "unscored"
    assert store.recorded == []


async def test_missing_citations_flag_supported_answer():
    store = FakeStore(_msg(content="Paris is the capital of France.", source_count=1))
    status = await _consumer(store, FakeJudge(score=0.95)).handle({"message_id": "m6"})
    assert status == "flagged"
    result = store.recorded[0][2]
    assert result["citation_validity_score"] == 0.0
    assert result["citation_coverage_score"] == 0.0


async def test_invalid_citation_index_flags():
    store = FakeStore(_msg(content="Paris is the capital of France [2].", source_count=1))
    status = await _consumer(store, FakeJudge(score=0.95)).handle({"message_id": "m7"})
    assert status == "flagged"
    result = store.recorded[0][2]
    assert result["citation_validity_score"] == 0.0
    assert result["details"]["citation"]["invalid_indices"] == [2]


class FakeBus:
    def __init__(self):
        self.acked = []

    async def ensure_group(self, *_args):
        return None

    async def consume(self, *_args):
        return [("stream-1", {"message_id": "m8"})]

    async def ack(self, *_args):
        self.acked.append(_args[-1])

    async def delivery_count(self, *_args):
        return 1  # first delivery


async def test_judge_error_is_not_acked_for_redelivery():
    bus = FakeBus()
    consumer = _consumer(FakeStore(_msg()), FakeJudge(raises=True))
    consumer.bus = bus
    assert await consumer.run_once() == 1
    assert bus.acked == []


class NotScoredJudge:
    """What FaithfulnessJudge returns when the model misses its time budget."""

    async def score(self, answer, context):
        return None


async def test_judge_timeout_records_citations_and_acks():
    bus = FakeBus()
    store = FakeStore(_msg())
    consumer = _consumer(store, NotScoredJudge())
    consumer.bus = bus
    assert await consumer.run_once() == 1
    assert bus.acked == ["stream-1"]  # no redelivery loop
    result = store.recorded[0][2]
    assert result["faithfulness_score"] is None
    assert result["citation_validity_score"] == 1.0
    assert result["flagged"] is False


class CountingBus(FakeBus):
    def __init__(self, deliveries):
        super().__init__()
        self.deliveries = deliveries

    async def delivery_count(self, *_args):
        return self.deliveries


def _capped_consumer(deliveries, max_deliveries=5):
    bus = CountingBus(deliveries)
    store = FakeStore(_msg())
    consumer = _consumer(store, FakeJudge(raises=True))
    consumer.bus = bus
    consumer.max_deliveries = max_deliveries
    return consumer, bus, store


# An unreachable or failing judge is retried while the event is under the cap:
# outages recover and the answer still gets scored.
async def test_judge_error_under_delivery_cap_is_redelivered():
    consumer, bus, store = _capped_consumer(deliveries=4)
    assert await consumer.run_once() == 1
    assert bus.acked == []
    assert store.recorded == []


# At the cap the event stops cycling: acked and recorded without faithfulness.
async def test_judge_error_at_delivery_cap_is_acked_unscored():
    consumer, bus, store = _capped_consumer(deliveries=5)
    assert await consumer.run_once() == 1
    assert bus.acked == ["stream-1"]
    result = store.recorded[0][2]
    assert result["faithfulness_score"] is None
    assert result["citation_validity_score"] == 1.0
    assert result["flagged"] is False
