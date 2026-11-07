# SPDX-License-Identifier: Apache-2.0

from raggie_workers.evaluation.judge import parse_score
from raggie_workers.evaluation.sampler import ThroughputSampler


def test_under_threshold_keeps_all():
    s = ThroughputSampler(qps_threshold=5, sample_rate=1.0)
    assert all(s.should(0.0) for _ in range(5))


def test_over_threshold_full_rate_keeps_all():
    s = ThroughputSampler(qps_threshold=0, sample_rate=1.0)  # always "over"
    assert all(s.should(0.0) for _ in range(6))  # stride 1 -> keep everything


def test_over_threshold_half_rate_keeps_every_other():
    s = ThroughputSampler(qps_threshold=0, sample_rate=0.5)  # stride 2
    decisions = [s.should(0.0) for _ in range(4)]
    assert decisions == [False, True, False, True]


def test_zero_rate_drops_when_over_threshold():
    s = ThroughputSampler(qps_threshold=0, sample_rate=0.0)
    assert not any(s.should(0.0) for _ in range(4))


def test_window_resets_after_a_second():
    s = ThroughputSampler(qps_threshold=1, sample_rate=0.0)
    assert s.should(0.0) is True  # first fills the window
    assert s.should(0.5) is False  # still within 1s, over threshold, rate 0
    assert s.should(2.0) is True  # window aged out -> under threshold again


def test_parse_score():
    assert parse_score("0.85") == 0.85
    assert parse_score("The score is 0.3.") == 0.3
    assert parse_score("1") == 1.0
    assert parse_score("nonsense") is None
    assert parse_score("1.7") == 1.0  # clamped
