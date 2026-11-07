// SPDX-License-Identifier: Apache-2.0

// Package ratelimit implements a sliding-window request limiter (the
// two-bucket "sliding window counter" approximation) with a Redis backend
// shared by every edge replica and an in-memory backend for tests.
//
// The estimate for a key is prev*(window-elapsed)/window + cur, where cur/prev
// are the request counts of the current/previous fixed window. It smooths the
// 2x burst a plain fixed window allows at boundaries, at O(1) memory per key.
package ratelimit

import (
	"context"
	"math"
	"strconv"
	"sync"
	"time"

	"github.com/redis/go-redis/v9"
)

// Decision is the outcome of one Allow call. RetryAfter is set when denied.
type Decision struct {
	Allowed    bool
	RetryAfter time.Duration
}

// Limiter admits or rejects one request for key under limit-per-window.
// A non-positive limit means unlimited. Errors (e.g. Redis down) are returned
// alongside an allowing Decision; callers decide whether to fail open.
type Limiter interface {
	Allow(ctx context.Context, key string, limit int, window time.Duration) (Decision, error)
}

// decide applies the sliding-window estimate. When denied it returns how long
// until one more request fits (at least 1s, for a useful Retry-After).
func decide(limit int64, window, elapsed time.Duration, cur, prev int64) (bool, time.Duration) {
	win := float64(window)
	weight := (win - float64(elapsed)) / win
	if float64(prev)*weight+float64(cur)+1 <= float64(limit) {
		return true, 0
	}
	var wait float64
	if room := float64(limit - 1 - cur); room >= 0 && prev > 0 {
		// Still fits in this window once enough of prev has aged out.
		wait = (win - room*win/float64(prev)) - float64(elapsed)
	} else {
		// Wait for the next window, where cur becomes the weighted prev.
		wait = win - float64(elapsed)
		if cur > 0 {
			wait += math.Max(0, win-float64(limit-1)*win/float64(cur))
		}
	}
	retry := time.Duration(math.Ceil(wait/float64(time.Second))) * time.Second
	if retry < time.Second {
		retry = time.Second
	}
	return false, retry
}

// windowPosition returns the index of the fixed window containing now and how
// far into it now is.
func windowPosition(now time.Time, window time.Duration) (int64, time.Duration) {
	ms := now.UnixMilli()
	w := window.Milliseconds()
	return ms / w, time.Duration(ms%w) * time.Millisecond
}

// ── Redis ─────────────────────────────────────────────────────────────────

// slidingWindowScript reads both window counters and increments the current one
// only when the request is admitted, atomically. Keys share a {hash tag} so the
// script is Redis Cluster safe.
var slidingWindowScript = redis.NewScript(`
local limit = tonumber(ARGV[1])
local win = tonumber(ARGV[2])
local elapsed = tonumber(ARGV[3])
local cur = tonumber(redis.call('GET', KEYS[1]) or '0')
local prev = tonumber(redis.call('GET', KEYS[2]) or '0')
if prev * (win - elapsed) / win + cur + 1 > limit then
  return {0, cur, prev}
end
cur = redis.call('INCR', KEYS[1])
redis.call('PEXPIRE', KEYS[1], win * 2)
return {1, cur, prev}
`)

// Redis is the production Limiter, shared across replicas.
type Redis struct {
	rdb    redis.Scripter
	prefix string
	now    func() time.Time
}

// NewRedis builds a Redis-backed limiter; keys are namespaced under prefix.
func NewRedis(rdb redis.Scripter, prefix string) *Redis {
	return &Redis{rdb: rdb, prefix: prefix, now: time.Now}
}

// WithClock overrides the clock (tests).
func (r *Redis) WithClock(now func() time.Time) *Redis {
	r.now = now
	return r
}

func (r *Redis) Allow(ctx context.Context, key string, limit int, window time.Duration) (Decision, error) {
	if limit <= 0 {
		return Decision{Allowed: true}, nil
	}
	idx, elapsed := windowPosition(r.now(), window)
	base := r.prefix + ":{" + key + "}:"
	res, err := slidingWindowScript.Run(ctx, r.rdb,
		[]string{base + strconv.FormatInt(idx, 10), base + strconv.FormatInt(idx-1, 10)},
		limit, window.Milliseconds(), elapsed.Milliseconds(),
	).Int64Slice()
	if err != nil || len(res) != 3 {
		return Decision{Allowed: true}, err
	}
	if res[0] == 1 {
		return Decision{Allowed: true}, nil
	}
	_, retry := decide(int64(limit), window, elapsed, res[1], res[2])
	return Decision{RetryAfter: retry}, nil
}

// ── In-memory ─────────────────────────────────────────────────────────────

// Memory is a single-process Limiter for tests. Keys are pruned only when
// touched again, so it is not meant for long-running production use.
type Memory struct {
	mu     sync.Mutex
	now    func() time.Time
	counts map[string]map[int64]int64 // key -> window index -> count
}

func NewMemory(now func() time.Time) *Memory {
	return &Memory{now: now, counts: map[string]map[int64]int64{}}
}

func (m *Memory) Allow(_ context.Context, key string, limit int, window time.Duration) (Decision, error) {
	if limit <= 0 {
		return Decision{Allowed: true}, nil
	}
	idx, elapsed := windowPosition(m.now(), window)
	m.mu.Lock()
	defer m.mu.Unlock()
	windows := m.counts[key]
	if windows == nil {
		windows = map[int64]int64{}
		m.counts[key] = windows
	}
	for w := range windows {
		if w < idx-1 {
			delete(windows, w)
		}
	}
	allowed, retry := decide(int64(limit), window, elapsed, windows[idx], windows[idx-1])
	if !allowed {
		return Decision{RetryAfter: retry}, nil
	}
	windows[idx]++
	return Decision{Allowed: true}, nil
}
