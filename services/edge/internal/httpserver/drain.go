// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"sync"
	"time"
)

// ErrShutdownDrain is the cancellation cause of streams still running when the
// shutdown drain window elapses. Handlers detect it (drainCancelled) to end the
// SSE stream with a "reconnect" event instead of an error.
var ErrShutdownDrain = errors.New("edge shutting down: drain window elapsed")

// Drainer coordinates graceful shutdown of long-lived SSE streams:
//  0. MarkNotReady (optional delay phase) fails readiness while new streams
//     are still served, so endpoint removal can propagate;
//  1. StartDrain also makes Track reject new streams (503 + Retry-After);
//  2. Wait lets in-flight streams finish within the drain window;
//  3. CancelAll cancels the stragglers with ErrShutdownDrain so each handler
//     can tell its client to reconnect (to another replica).
type Drainer struct {
	mu       sync.Mutex
	notReady bool
	draining bool
	nextID   uint64
	streams  map[uint64]context.CancelCauseFunc
	changed  chan struct{} // closed (and replaced) whenever a stream ends
}

func NewDrainer() *Drainer {
	return &Drainer{streams: map[uint64]context.CancelCauseFunc{}, changed: make(chan struct{})}
}

// Track registers a new stream. It returns a context that CancelAll can
// cancel, an idempotent release func, and ok=false once draining has begun.
func (d *Drainer) Track(parent context.Context) (context.Context, func(), bool) {
	d.mu.Lock()
	defer d.mu.Unlock()
	if d.draining {
		return parent, func() {}, false
	}
	ctx, cancel := context.WithCancelCause(parent)
	id := d.nextID
	d.nextID++
	d.streams[id] = cancel
	var once sync.Once
	release := func() {
		once.Do(func() {
			d.mu.Lock()
			delete(d.streams, id)
			close(d.changed)
			d.changed = make(chan struct{})
			d.mu.Unlock()
			cancel(nil)
		})
	}
	return ctx, release, true
}

// MarkNotReady fails readiness but keeps admitting streams. Idempotent.
func (d *Drainer) MarkNotReady() {
	d.mu.Lock()
	d.notReady = true
	d.mu.Unlock()
}

// NotReady reports whether readiness must fail (not ready or draining).
func (d *Drainer) NotReady() bool {
	d.mu.Lock()
	defer d.mu.Unlock()
	return d.notReady || d.draining
}

// StartDrain stops admitting new streams and fails readiness. Idempotent.
func (d *Drainer) StartDrain() {
	d.mu.Lock()
	d.notReady = true
	d.draining = true
	d.mu.Unlock()
}

func (d *Drainer) Draining() bool {
	d.mu.Lock()
	defer d.mu.Unlock()
	return d.draining
}

// Active is the number of in-flight streams.
func (d *Drainer) Active() int {
	d.mu.Lock()
	defer d.mu.Unlock()
	return len(d.streams)
}

// Wait blocks until no stream is in flight or ctx ends (returning ctx's error).
func (d *Drainer) Wait(ctx context.Context) error {
	for {
		d.mu.Lock()
		if len(d.streams) == 0 {
			d.mu.Unlock()
			return nil
		}
		changed := d.changed
		d.mu.Unlock()
		select {
		case <-changed:
		case <-ctx.Done():
			return ctx.Err()
		}
	}
}

// CancelAll cancels every in-flight stream with ErrShutdownDrain.
func (d *Drainer) CancelAll() {
	d.mu.Lock()
	defer d.mu.Unlock()
	for _, cancel := range d.streams {
		cancel(ErrShutdownDrain)
	}
}

// ShutdownPlan sizes the shutdown phases.
type ShutdownPlan struct {
	Delay       time.Duration // not-ready but still serving (endpoint propagation)
	Drain       time.Duration // new streams refused; in-flight ones may finish
	ForcedGrace time.Duration // after CancelAll, time for handlers to write "reconnect"
}

// Shutdown runs the stream shutdown sequence (MarkNotReady → delay →
// StartDrain → wait → CancelAll → grace) and returns how many streams had to
// be force-cancelled. ctx aborts the remaining waits early (e.g. a second
// signal); the drain phase then still ends with CancelAll.
func (d *Drainer) Shutdown(ctx context.Context, plan ShutdownPlan, logger *slog.Logger) int {
	d.MarkNotReady()
	if plan.Delay > 0 {
		logger.Info("shutdown delay: readiness failing, still serving", "delay", plan.Delay.String())
		select {
		case <-time.After(plan.Delay):
		case <-ctx.Done():
		}
	}
	logger.Info("draining streams", "active_streams", d.Active(), "drain", plan.Drain.String())
	d.StartDrain()
	drainCtx, cancel := context.WithTimeout(ctx, plan.Drain)
	defer cancel()
	if d.Wait(drainCtx) == nil {
		return 0
	}
	forced := d.Active()
	logger.Warn("drain window elapsed; asking remaining streams to reconnect", "remaining", forced)
	d.CancelAll()
	graceCtx, cancelGrace := context.WithTimeout(context.Background(), plan.ForcedGrace)
	defer cancelGrace()
	_ = d.Wait(graceCtx)
	return forced
}

// drainCancelled reports whether ctx was cancelled by the shutdown drain.
func drainCancelled(ctx context.Context) bool {
	return errors.Is(context.Cause(ctx), ErrShutdownDrain)
}

// drainRetryAfterSeconds is the Retry-After hint while draining: long enough
// for the load balancer to drop this replica, short enough to feel instant.
const drainRetryAfterSeconds = 2

// writeReconnectEvent ends a drained SSE stream with an explicit instruction to
// reconnect (the partial answer is already persisted). Caller flushes.
// It names the interrupted assistant message so the client can resume it with
// resume_message_id instead of re-sending the question.
func writeReconnectEvent(w http.ResponseWriter, r *http.Request, t botTurn) {
	fmt.Fprintf(w, "event: reconnect\ndata: %s\n\n", mustJSON(map[string]any{
		"reason":          "server_shutdown",
		"retry_after_ms":  drainRetryAfterSeconds * 1000,
		"conversation_id": t.conversationID,
		"message_id":      t.messageID,
		"code":            errCodeDraining,
		"message":         errorMessage(r.Context(), errCodeDraining),
	}))
}
