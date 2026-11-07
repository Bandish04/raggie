// SPDX-License-Identifier: Apache-2.0

package rag

import (
	"testing"
	"time"
)

func TestA2LatencyBudget(t *testing.T) {
	for _, tc := range []struct {
		env  string
		want time.Duration
	}{
		{"", 200 * time.Millisecond},
		{"350", 350 * time.Millisecond},
		{"0", 200 * time.Millisecond},
		{"-5", 200 * time.Millisecond},
		{"abc", 200 * time.Millisecond},
	} {
		t.Setenv("A2_LATENCY_BUDGET_MS", tc.env)
		if got := a2LatencyBudget(); got != tc.want {
			t.Errorf("A2_LATENCY_BUDGET_MS=%q: budget = %s, want %s", tc.env, got, tc.want)
		}
	}
}

func TestPercentileNearestRank(t *testing.T) {
	samples := make([]time.Duration, 0, 100)
	for i := 100; i >= 1; i-- { // unsorted on purpose
		samples = append(samples, time.Duration(i)*time.Millisecond)
	}
	if got := percentile(samples, 95); got != 95*time.Millisecond {
		t.Fatalf("p95 = %s, want 95ms", got)
	}
	if got := percentile(samples, 100); got != 100*time.Millisecond {
		t.Fatalf("p100 = %s, want 100ms", got)
	}
	if samples[0] != 100*time.Millisecond {
		t.Fatal("percentile must not reorder the caller's slice")
	}
	if got := percentile([]time.Duration{7 * time.Millisecond}, 95); got != 7*time.Millisecond {
		t.Fatalf("single-sample p95 = %s", got)
	}
	if got := percentile(nil, 95); got != 0 {
		t.Fatalf("empty p95 = %s, want 0", got)
	}
}

func TestLatencySkipReason(t *testing.T) {
	t.Setenv("RAGGIE_SKIP_LATENCY_TESTS", "1")
	if latencySkipReason() == "" {
		t.Fatal("RAGGIE_SKIP_LATENCY_TESTS=1 must skip latency assertions")
	}
	t.Setenv("RAGGIE_SKIP_LATENCY_TESTS", "")
	if got := latencySkipReason(); (got != "") != raceEnabled {
		t.Fatalf("skip reason = %q with raceEnabled=%v; only the race detector should skip", got, raceEnabled)
	}
}
