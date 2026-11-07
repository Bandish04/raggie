// SPDX-License-Identifier: Apache-2.0

package ratelimit

import (
	"context"
	"fmt"
	"os"
	"testing"
	"time"

	"github.com/redis/go-redis/v9"
)

// fakeClock is a manually advanced clock for deterministic window tests.
type fakeClock struct{ now time.Time }

func (c *fakeClock) Now() time.Time          { return c.now }
func (c *fakeClock) Advance(d time.Duration) { c.now = c.now.Add(d) }

func TestDecideSlidingWindow(t *testing.T) {
	win := time.Minute
	cases := []struct {
		name               string
		limit, cur, prev   int64
		elapsed            time.Duration
		wantAllowed        bool
		minRetry, maxRetry time.Duration
	}{
		{"empty window", 5, 0, 0, 0, true, 0, 0},
		{"last slot", 5, 4, 0, 30 * time.Second, true, 0, 0},
		// Full now; in the next window the 5 requests still weigh until 12s in:
		// 30s (rest of this window) + 12s.
		{"full current window", 5, 5, 0, 30 * time.Second, false, 42 * time.Second, 43 * time.Second},
		// prev=10 weighted at 50% = 5 -> full; frees up as the previous window ages out.
		{"previous window still weighs", 5, 0, 10, 30 * time.Second, false, time.Second, 30 * time.Second},
		{"previous window mostly aged out", 5, 0, 10, 55 * time.Second, true, 0, 0},
	}
	for _, tc := range cases {
		allowed, retry := decide(tc.limit, win, tc.elapsed, tc.cur, tc.prev)
		if allowed != tc.wantAllowed {
			t.Errorf("%s: allowed=%v want %v", tc.name, allowed, tc.wantAllowed)
			continue
		}
		if !allowed && (retry < tc.minRetry || retry > tc.maxRetry) {
			t.Errorf("%s: retry=%v want in [%v,%v]", tc.name, retry, tc.minRetry, tc.maxRetry)
		}
		if !allowed && retry < time.Second {
			t.Errorf("%s: retry must be at least 1s, got %v", tc.name, retry)
		}
	}
}

func exerciseLimiter(t *testing.T, l Limiter, clock *fakeClock, key string) {
	t.Helper()
	ctx := context.Background()
	for i := 0; i < 3; i++ {
		d, err := l.Allow(ctx, key, 3, time.Minute)
		if err != nil || !d.Allowed {
			t.Fatalf("request %d should pass: %+v %v", i+1, d, err)
		}
	}
	d, err := l.Allow(ctx, key, 3, time.Minute)
	if err != nil || d.Allowed || d.RetryAfter <= 0 {
		t.Fatalf("4th request should be limited with a Retry-After: %+v %v", d, err)
	}
	// Other keys are independent.
	if d, err := l.Allow(ctx, key+":other", 3, time.Minute); err != nil || !d.Allowed {
		t.Fatalf("independent key limited: %+v %v", d, err)
	}
	// Two full windows later the history has aged out entirely.
	clock.Advance(2 * time.Minute)
	if d, err := l.Allow(ctx, key, 3, time.Minute); err != nil || !d.Allowed {
		t.Fatalf("should pass after the window slides: %+v %v", d, err)
	}
}

func TestMemoryLimiter(t *testing.T) {
	clock := &fakeClock{now: time.Unix(1_700_000_000, 0)}
	exerciseLimiter(t, NewMemory(clock.Now), clock, "k")
}

func TestLimiterRejectsNonPositiveLimit(t *testing.T) {
	l := NewMemory(time.Now)
	if d, err := l.Allow(context.Background(), "k", 0, time.Minute); err != nil || !d.Allowed {
		t.Fatalf("limit 0 means unlimited: %+v %v", d, err)
	}
}

// Live Redis test; skipped unless REDIS_URL is set.
func TestRedisLimiter(t *testing.T) {
	url := os.Getenv("REDIS_URL")
	if url == "" {
		t.Skip("REDIS_URL not set")
	}
	opt, err := redis.ParseURL(url)
	if err != nil {
		t.Fatal(err)
	}
	rdb := redis.NewClient(opt)
	defer rdb.Close()
	clock := &fakeClock{now: time.Unix(1_700_000_000, 0)}
	l := NewRedis(rdb, fmt.Sprintf("rltest:%d", time.Now().UnixNano())).WithClock(clock.Now)
	exerciseLimiter(t, l, clock, "k")
}

// A Redis outage surfaces as an error (the caller fails open), never a panic.
func TestRedisLimiterReportsErrors(t *testing.T) {
	rdb := redis.NewClient(&redis.Options{Addr: "127.0.0.1:1", DialTimeout: 100 * time.Millisecond, MaxRetries: -1})
	defer rdb.Close()
	if _, err := NewRedis(rdb, "rl").Allow(context.Background(), "k", 3, time.Minute); err == nil {
		t.Fatal("expected an error when Redis is unreachable")
	}
}
