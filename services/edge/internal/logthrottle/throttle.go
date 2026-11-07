// SPDX-License-Identifier: Apache-2.0

// Package logthrottle rate-limits repetitive operator warnings on hot paths
// (e.g. a reranker failing open on every chat turn) so a degraded dependency
// is visible in the logs without flooding them.
package logthrottle

import (
	"sync"
	"time"
)

// Throttle allows at most one event per interval and counts the events it
// suppressed in between. The zero interval allows every event. Safe for
// concurrent use.
type Throttle struct {
	interval time.Duration
	now      func() time.Time

	mu         sync.Mutex
	last       time.Time
	suppressed int64
}

// New returns a Throttle allowing one event per interval.
func New(interval time.Duration) *Throttle {
	return &Throttle{interval: interval, now: time.Now}
}

// Allow reports whether the caller should log this event and, when it should,
// how many events were suppressed since the previous allowed one.
func (t *Throttle) Allow() (bool, int64) {
	t.mu.Lock()
	defer t.mu.Unlock()
	now := t.now()
	if !t.last.IsZero() && now.Sub(t.last) < t.interval {
		t.suppressed++
		return false, 0
	}
	suppressed := t.suppressed
	t.last, t.suppressed = now, 0
	return true, suppressed
}
