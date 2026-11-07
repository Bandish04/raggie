// SPDX-License-Identifier: Apache-2.0

package rag

import (
	"math"
	"os"
	"slices"
	"strconv"
	"time"
)

// defaultA2Budget is the A2 retrieval p95 target (embed + search + assembly).
const defaultA2Budget = 200 * time.Millisecond

// a2LatencyBudget is the p95 budget for the live A2 check: A2_LATENCY_BUDGET_MS
// when it is a positive integer, else defaultA2Budget. Slower shared runners
// can widen it without editing the test.
func a2LatencyBudget() time.Duration {
	if ms, err := strconv.Atoi(os.Getenv("A2_LATENCY_BUDGET_MS")); err == nil && ms > 0 {
		return time.Duration(ms) * time.Millisecond
	}
	return defaultA2Budget
}

// latencySkipReason returns why wall-clock latency assertions must not run in
// this test binary, or "" when they should. The authoritative A2 proof is the
// bench/ harness; this is a regression tripwire for nightly/benchmark runs.
func latencySkipReason() string {
	switch {
	case os.Getenv("RAGGIE_SKIP_LATENCY_TESTS") == "1":
		return "RAGGIE_SKIP_LATENCY_TESTS=1"
	case raceEnabled:
		return "race detector enabled: latency is not representative"
	}
	return ""
}

// percentile returns the nearest-rank p-th percentile (0 < p <= 100) of
// samples without reordering them; 0 for no samples.
func percentile(samples []time.Duration, p float64) time.Duration {
	if len(samples) == 0 {
		return 0
	}
	sorted := slices.Clone(samples)
	slices.Sort(sorted)
	rank := int(math.Ceil(float64(len(sorted))*p/100)) - 1
	return sorted[max(0, min(rank, len(sorted)-1))]
}
