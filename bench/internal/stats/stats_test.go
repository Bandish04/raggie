// SPDX-License-Identifier: Apache-2.0

package stats

import (
	"testing"
	"time"
)

func ms(n int) time.Duration { return time.Duration(n) * time.Millisecond }

func TestSummarizeNearestRank(t *testing.T) {
	samples := make([]time.Duration, 0, 100)
	for i := 100; i >= 1; i-- { // unsorted on purpose
		samples = append(samples, ms(i))
	}
	s := Summarize(samples)
	if s.N != 100 || s.Min != ms(1) || s.Max != ms(100) {
		t.Fatalf("n/min/max = %d/%s/%s", s.N, s.Min, s.Max)
	}
	if s.P50 != ms(50) || s.P90 != ms(90) || s.P95 != ms(95) || s.P99 != ms(99) {
		t.Fatalf("percentiles = p50 %s p90 %s p95 %s p99 %s", s.P50, s.P90, s.P95, s.P99)
	}
	if s.Mean != 50500*time.Microsecond {
		t.Fatalf("mean = %s, want 50.5ms", s.Mean)
	}
	if samples[0] != ms(100) {
		t.Fatal("Summarize must not reorder the caller's slice")
	}
}

func TestSummarizeSmallAndEmpty(t *testing.T) {
	if s := Summarize(nil); s.N != 0 || s.P95 != 0 {
		t.Fatalf("empty summary = %+v", s)
	}
	s := Summarize([]time.Duration{ms(7)})
	if s.P50 != ms(7) || s.P99 != ms(7) || s.Mean != ms(7) {
		t.Fatalf("single-sample summary = %+v", s)
	}
}

func TestPercentileBounds(t *testing.T) {
	sorted := []time.Duration{ms(1), ms(2), ms(3), ms(4)}
	for _, tc := range []struct {
		p    float64
		want time.Duration
	}{{0, ms(1)}, {25, ms(1)}, {50, ms(2)}, {75, ms(3)}, {100, ms(4)}, {150, ms(4)}} {
		if got := Percentile(sorted, tc.p); got != tc.want {
			t.Errorf("p%v = %s, want %s", tc.p, got, tc.want)
		}
	}
}

func TestMillisRow(t *testing.T) {
	s := Summarize([]time.Duration{ms(1), ms(3)})
	row := s.MillisRow()
	want := []string{"2", "1.000", "2.000", "1.000", "3.000", "3.000", "3.000", "3.000"}
	if len(row) != len(want) {
		t.Fatalf("row = %v", row)
	}
	for i := range want {
		if row[i] != want[i] {
			t.Fatalf("row = %v, want %v", row, want)
		}
	}
	if len(SummaryHeader) != len(row) {
		t.Fatalf("header/row length mismatch: %v vs %v", SummaryHeader, row)
	}
}

func TestRatio(t *testing.T) {
	if Ratio(0, 0) != 0 || Ratio(1, 4) != 0.25 {
		t.Fatal("Ratio")
	}
}
