// SPDX-License-Identifier: Apache-2.0

package ratelimit

import (
	"testing"
	"time"
)

// The sliding-window decision never panics and a denial always carries a
// usable Retry-After (>= 1s, bounded by two windows).
func FuzzDecide(f *testing.F) {
	f.Add(int64(5), int64(60000), int64(30000), int64(5), int64(0))
	f.Add(int64(1), int64(1), int64(0), int64(0), int64(1<<40))
	f.Fuzz(func(t *testing.T, limit, windowMs, elapsedMs, cur, prev int64) {
		if limit < 1 || windowMs < 1 || windowMs > int64(24*time.Hour/time.Millisecond) ||
			elapsedMs < 0 || elapsedMs >= windowMs || cur < 0 || prev < 0 || cur > 1<<40 || prev > 1<<40 {
			return
		}
		window := time.Duration(windowMs) * time.Millisecond
		allowed, retry := decide(limit, window, time.Duration(elapsedMs)*time.Millisecond, cur, prev)
		if allowed {
			if cur+1 > limit {
				t.Fatalf("admitted with cur=%d limit=%d", cur, limit)
			}
			return
		}
		if retry < time.Second || retry > 2*window+time.Second {
			t.Fatalf("retry %v outside [1s, 2w] for window %v", retry, window)
		}
	})
}
