// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"sync"
	"sync/atomic"
)

// StreamLimiter caps concurrent chat SSE streams on one replica
// (EDGE_MAX_SSE_CONNECTIONS). Past the cap a new chat is shed with a retryable
// 503 busy before any stream byte, so a traffic spike degrades into retries
// instead of exhausting memory and file descriptors. A nil limiter, or a limit
// of 0, admits everything.
type StreamLimiter struct {
	limit    int64
	open     atomic.Int64
	rejected atomic.Int64
}

func NewStreamLimiter(limit int) *StreamLimiter {
	return &StreamLimiter{limit: int64(max(limit, 0))}
}

// Acquire claims a stream slot. ok=false means the replica is at its cap; the
// release func is idempotent and must be called when the stream ends.
func (l *StreamLimiter) Acquire() (release func(), ok bool) {
	if l == nil {
		return func() {}, true
	}
	if n := l.open.Add(1); l.limit > 0 && n > l.limit {
		l.open.Add(-1)
		l.rejected.Add(1)
		return func() {}, false
	}
	var once sync.Once
	return func() { once.Do(func() { l.open.Add(-1) }) }, true
}

// Stats reports open streams, the configured cap (0 = unlimited) and how many
// streams were shed at the cap.
func (l *StreamLimiter) Stats() (open, limit, rejected int64) {
	return l.open.Load(), l.limit, l.rejected.Load()
}
