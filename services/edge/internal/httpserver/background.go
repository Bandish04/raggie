// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"context"
	"errors"
	"log/slog"
	"sync"
	"sync/atomic"
	"time"
)

var errBackgroundDrainTimeout = errors.New("background jobs did not drain before timeout")

// BackgroundJobs bounds best-effort post-response work. Jobs are admitted only
// when a slot is available; callers never wait and the number of goroutines is
// capped by construction.
type BackgroundJobs struct {
	logger  *slog.Logger
	timeout time.Duration
	slots   chan struct{}

	mu     sync.Mutex
	closed bool
	wg     sync.WaitGroup

	active  atomic.Int64
	dropped atomic.Int64
}

func NewBackgroundJobs(maxConcurrency int, timeout time.Duration, logger *slog.Logger) *BackgroundJobs {
	if maxConcurrency <= 0 {
		maxConcurrency = 1
	}
	if timeout <= 0 {
		timeout = 30 * time.Second
	}
	if logger == nil {
		logger = slog.Default()
	}
	return &BackgroundJobs{
		logger:  logger,
		timeout: timeout,
		slots:   make(chan struct{}, maxConcurrency),
	}
}

// TryGo starts fn when capacity is available. It returns false when the work is
// shed because the limiter is full or shutting down.
func (b *BackgroundJobs) TryGo(name string, fn func(context.Context)) bool {
	if b == nil || fn == nil {
		return false
	}

	b.mu.Lock()
	if b.closed {
		b.dropped.Add(1)
		b.mu.Unlock()
		return false
	}
	select {
	case b.slots <- struct{}{}:
		b.wg.Add(1)
	default:
		b.dropped.Add(1)
		b.mu.Unlock()
		return false
	}
	b.mu.Unlock()

	b.active.Add(1)
	go func() {
		defer func() {
			if recovered := recover(); recovered != nil {
				b.logger.Error("background job panicked", "job", name, "err", recovered)
			}
			b.active.Add(-1)
			<-b.slots
			b.wg.Done()
		}()

		ctx, cancel := context.WithTimeout(context.Background(), b.timeout)
		defer cancel()
		fn(ctx)
	}()
	return true
}

// Stats returns instantaneous active work and the cumulative number of jobs
// shed since process start.
func (b *BackgroundJobs) Stats() (active, dropped int64) {
	if b == nil {
		return 0, 0
	}
	return b.active.Load(), b.dropped.Load()
}

// Shutdown stops new admissions and waits for active jobs to finish.
func (b *BackgroundJobs) Shutdown(ctx context.Context) error {
	if b == nil {
		return nil
	}
	b.mu.Lock()
	b.closed = true
	b.mu.Unlock()

	done := make(chan struct{})
	go func() {
		b.wg.Wait()
		close(done)
	}()
	select {
	case <-done:
		return nil
	case <-ctx.Done():
		return errBackgroundDrainTimeout
	}
}
