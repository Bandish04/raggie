// SPDX-License-Identifier: Apache-2.0

package harness

import (
	"context"
	"errors"
	"sort"
	"sync"
	"time"

	"github.com/alicangunduz/raggie/bench/internal/stack"
	"github.com/alicangunduz/raggie/bench/internal/stats"
)

// ErrRateLimited aborts a run whose stack rate-limits the benchmark user.
var ErrRateLimited = errors.New("the edge rate-limited the benchmark (HTTP 429 rate_limited): restart the stack with " +
	"RATE_LIMIT_ENABLED=false (see docs/benchmarks/README.md), or pace requests with -pace")

// Series is one named latency distribution (rendered by the "latency-row"
// template).
type Series struct {
	Name string
	S    stats.Summary
}

// PhaseSeries summarizes the phase offsets of the completed turns.
func PhaseSeries(results []stack.ChatResult) []Series {
	var headers, meta, sources, first, done []time.Duration
	for _, r := range results {
		if !r.OK() {
			continue
		}
		headers = append(headers, r.Headers)
		meta = append(meta, r.Meta)
		sources = append(sources, r.Sources)
		first = append(first, r.FirstToken)
		done = append(done, r.Done)
	}
	return []Series{
		{"headers", stats.Summarize(headers)},
		{"meta event", stats.Summarize(meta)},
		{"sources", stats.Summarize(sources)},
		{"first token", stats.Summarize(first)},
		{"done", stats.Summarize(done)},
	}
}

// Outcome counts one result class.
type Outcome struct {
	Name  string
	Count int
}

// Outcomes breaks results down by class, most frequent first.
func Outcomes(results []stack.ChatResult) []Outcome {
	counts := map[string]int{}
	for _, r := range results {
		counts[r.Outcome()]++
	}
	out := make([]Outcome, 0, len(counts))
	for k, v := range counts {
		out = append(out, Outcome{k, v})
	}
	sort.Slice(out, func(i, j int) bool {
		if out[i].Count != out[j].Count {
			return out[i].Count > out[j].Count
		}
		return out[i].Name < out[j].Name
	})
	return out
}

// SuccessCount is the number of completed turns.
func SuccessCount(results []stack.ChatResult) int {
	n := 0
	for _, r := range results {
		if r.OK() {
			n++
		}
	}
	return n
}

// RunChats runs n turns with at most concurrency in flight, starting a new
// turn no sooner than pace after the previous start. Results keep the call
// order. A rate-limited turn aborts the run with ErrRateLimited.
func RunChats(ctx context.Context, n, concurrency int, pace time.Duration, fn func(context.Context, int) stack.ChatResult) ([]stack.ChatResult, error) {
	ctx, cancel := context.WithCancel(ctx)
	defer cancel()
	results := make([]stack.ChatResult, n)
	sem := make(chan struct{}, max(1, concurrency))
	var (
		wg      sync.WaitGroup
		once    sync.Once
		limited bool
	)
	var tick <-chan time.Time
	if pace > 0 {
		t := time.NewTicker(pace)
		defer t.Stop()
		tick = t.C
	}
	for i := 0; i < n; i++ {
		if i > 0 && tick != nil {
			select {
			case <-tick:
			case <-ctx.Done():
			}
		}
		select {
		case sem <- struct{}{}:
		case <-ctx.Done():
		}
		if ctx.Err() != nil {
			break
		}
		wg.Add(1)
		go func(i int) {
			defer func() { <-sem; wg.Done() }()
			r := fn(ctx, i)
			results[i] = r
			if r.ErrorCode == "rate_limited" {
				once.Do(func() { limited = true; cancel() })
			}
		}(i)
	}
	wg.Wait()
	if limited {
		return results, ErrRateLimited
	}
	return results, ctx.Err()
}
