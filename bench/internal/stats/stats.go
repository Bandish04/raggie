// SPDX-License-Identifier: Apache-2.0

// Package stats summarizes latency samples (nearest-rank percentiles) for the
// benchmark reports.
package stats

import (
	"math"
	"slices"
	"strconv"
	"time"
)

// Summary is the latency distribution of one measured series.
type Summary struct {
	N                             int
	Min, Mean, P50, P90, P95, P99 time.Duration
	Max                           time.Duration
}

// SummaryHeader names the columns of MillisRow.
var SummaryHeader = []string{"n", "min_ms", "mean_ms", "p50_ms", "p90_ms", "p95_ms", "p99_ms", "max_ms"}

// Summarize computes the distribution of samples without reordering them.
func Summarize(samples []time.Duration) Summary {
	if len(samples) == 0 {
		return Summary{}
	}
	sorted := slices.Clone(samples)
	slices.Sort(sorted)
	var total time.Duration
	for _, d := range sorted {
		total += d
	}
	return Summary{
		N:    len(sorted),
		Min:  sorted[0],
		Mean: total / time.Duration(len(sorted)),
		P50:  Percentile(sorted, 50),
		P90:  Percentile(sorted, 90),
		P95:  Percentile(sorted, 95),
		P99:  Percentile(sorted, 99),
		Max:  sorted[len(sorted)-1],
	}
}

// Percentile returns the nearest-rank p-th percentile of an ascending slice
// (p clamped to [0, 100]); 0 for no samples.
func Percentile(sorted []time.Duration, p float64) time.Duration {
	if len(sorted) == 0 {
		return 0
	}
	rank := int(math.Ceil(float64(len(sorted))*p/100)) - 1
	return sorted[max(0, min(rank, len(sorted)-1))]
}

// MillisRow renders the summary as CSV/markdown cells matching SummaryHeader.
func (s Summary) MillisRow() []string {
	return []string{
		strconv.Itoa(s.N), Millis(s.Min), Millis(s.Mean), Millis(s.P50),
		Millis(s.P90), Millis(s.P95), Millis(s.P99), Millis(s.Max),
	}
}

// Millis formats a duration as milliseconds with microsecond precision.
func Millis(d time.Duration) string {
	return strconv.FormatFloat(float64(d)/float64(time.Millisecond), 'f', 3, 64)
}

// Ratio is num/den, or 0 when den is 0.
func Ratio(num, den int) float64 {
	if den == 0 {
		return 0
	}
	return float64(num) / float64(den)
}
