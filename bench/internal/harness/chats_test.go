// SPDX-License-Identifier: Apache-2.0

package harness

import (
	"context"
	"errors"
	"net/http"
	"sync/atomic"
	"testing"
	"time"

	"github.com/alicangunduz/raggie/bench/internal/stack"
)

func ok(d time.Duration) stack.ChatResult {
	return stack.ChatResult{Status: http.StatusOK, Headers: d, Meta: d, Sources: d, FirstToken: 2 * d, Done: 3 * d, Total: 3 * d}
}

func TestPhaseSeriesOnlyCountsCompletedTurns(t *testing.T) {
	results := []stack.ChatResult{ok(10 * time.Millisecond), ok(20 * time.Millisecond), {Status: 503, ErrorCode: "busy"}}
	series := PhaseSeries(results)
	if len(series) != 5 || series[0].Name != "headers" || series[2].Name != "sources" || series[3].Name != "first token" {
		t.Fatalf("series = %+v", series)
	}
	if series[2].S.N != 2 || series[2].S.Max != 20*time.Millisecond {
		t.Fatalf("sources series = %+v", series[2].S)
	}
}

func TestOutcomesSortedByCount(t *testing.T) {
	results := []stack.ChatResult{ok(1), ok(1), {Status: 503, ErrorCode: "busy"}, ok(1)}
	out := Outcomes(results)
	if len(out) != 2 || out[0].Name != "ok" || out[0].Count != 3 || out[1].Name != "http_Service Unavailable:busy" {
		t.Fatalf("outcomes = %+v", out)
	}
	if SuccessCount(results) != 3 {
		t.Fatal("SuccessCount")
	}
}

func TestRunChatsBoundsConcurrencyAndKeepsOrder(t *testing.T) {
	var inflight, peak atomic.Int64
	results, err := RunChats(context.Background(), 20, 4, 0, func(_ context.Context, i int) stack.ChatResult {
		n := inflight.Add(1)
		defer inflight.Add(-1)
		for p := peak.Load(); n > p && !peak.CompareAndSwap(p, n); p = peak.Load() {
		}
		time.Sleep(2 * time.Millisecond)
		return stack.ChatResult{Tokens: i}
	})
	if err != nil {
		t.Fatal(err)
	}
	if peak.Load() > 4 {
		t.Fatalf("peak concurrency = %d, want ≤ 4", peak.Load())
	}
	for i, r := range results {
		if r.Tokens != i {
			t.Fatalf("results out of order at %d", i)
		}
	}
}

func TestRunChatsPacesRequests(t *testing.T) {
	start := time.Now()
	if _, err := RunChats(context.Background(), 4, 1, 20*time.Millisecond, func(context.Context, int) stack.ChatResult {
		return stack.ChatResult{}
	}); err != nil {
		t.Fatal(err)
	}
	if time.Since(start) < 60*time.Millisecond {
		t.Fatalf("4 paced requests finished in %s", time.Since(start))
	}
}

func TestRunChatsAbortsOnRateLimit(t *testing.T) {
	_, err := RunChats(context.Background(), 10, 1, 0, func(context.Context, int) stack.ChatResult {
		return stack.ChatResult{Status: http.StatusTooManyRequests, ErrorCode: "rate_limited"}
	})
	if !errors.Is(err, ErrRateLimited) {
		t.Fatalf("err = %v", err)
	}
}
