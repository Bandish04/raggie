# SPDX-License-Identifier: Apache-2.0

"""Throughput-based sampler: evaluate every chat up to a QPS
threshold; above it, keep a deterministic fraction so the eval lane degrades
gracefully under load instead of unbounded fan-out to the judge."""

from __future__ import annotations

from collections import deque


class ThroughputSampler:
    def __init__(self, qps_threshold: float = 20.0, sample_rate: float = 1.0) -> None:
        self._threshold = qps_threshold
        self._rate = max(0.0, min(1.0, sample_rate))
        # Deterministic stride: keep 1 of every `stride` once over the threshold.
        self._stride = round(1 / self._rate) if self._rate > 0 else 0
        self._recent: deque[float] = deque()  # eval timestamps in the last second
        self._over_count = 0

    def should(self, now: float) -> bool:
        recent = self._recent
        while recent and now - recent[0] > 1.0:
            recent.popleft()

        if len(recent) < self._threshold:
            recent.append(now)  # under load — evaluate everything
            return True

        # Over the threshold: sample at the configured rate.
        if self._stride == 0:
            return False
        self._over_count += 1
        keep = self._over_count % self._stride == 0
        if keep:
            recent.append(now)
        return keep
