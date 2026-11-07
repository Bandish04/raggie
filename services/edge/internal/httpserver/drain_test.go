// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/alicangunduz/raggie/services/edge/internal/config"
	"github.com/alicangunduz/raggie/services/edge/internal/ports"
	"github.com/alicangunduz/raggie/services/edge/internal/ports/mock"
	"github.com/alicangunduz/raggie/services/edge/internal/rag"
)

func TestDrainerTracksAndRejects(t *testing.T) {
	d := NewDrainer()
	ctx, release, ok := d.Track(context.Background())
	if !ok || d.Active() != 1 {
		t.Fatalf("track before drain: ok=%v active=%d", ok, d.Active())
	}
	d.StartDrain()
	if !d.Draining() {
		t.Fatal("expected draining")
	}
	if _, _, ok := d.Track(context.Background()); ok {
		t.Fatal("new streams must be rejected while draining")
	}

	// Wait blocks until the in-flight stream releases.
	waited := make(chan error, 1)
	go func() { waited <- d.Wait(context.Background()) }()
	select {
	case <-waited:
		t.Fatal("Wait returned with a stream still in flight")
	case <-time.After(30 * time.Millisecond):
	}
	if ctx.Err() != nil {
		t.Fatal("in-flight stream must not be cancelled by StartDrain")
	}
	release()
	release() // idempotent
	if err := <-waited; err != nil || d.Active() != 0 {
		t.Fatalf("Wait after release: err=%v active=%d", err, d.Active())
	}
}

func TestDrainerWaitTimesOutAndCancelAll(t *testing.T) {
	d := NewDrainer()
	ctx, release, _ := d.Track(context.Background())
	defer release()
	d.StartDrain()
	wctx, cancel := context.WithTimeout(context.Background(), 20*time.Millisecond)
	defer cancel()
	if err := d.Wait(wctx); !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("expected a timeout, got %v", err)
	}
	d.CancelAll()
	<-ctx.Done()
	if !errors.Is(context.Cause(ctx), ErrShutdownDrain) || !drainCancelled(ctx) {
		t.Fatalf("stream ctx cause = %v, want ErrShutdownDrain", context.Cause(ctx))
	}
}

func TestReadinessFailsImmediatelyWhenDraining(t *testing.T) {
	d := NewDrainer()
	deps := Deps{Drain: d}
	srv := New(config.Config{Port: "8080"}, discardLogger(), deps)
	get := func() int {
		rec := httptest.NewRecorder()
		srv.Handler.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/readyz", nil))
		return rec.Code
	}
	if code := get(); code != http.StatusOK {
		t.Fatalf("ready before drain: %d", code)
	}
	d.StartDrain()
	if code := get(); code != http.StatusServiceUnavailable {
		t.Fatalf("readyz while draining: expected 503, got %d", code)
	}
	// Liveness stays green: the process is healthy, just leaving rotation.
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/healthz", nil))
	if rec.Code != http.StatusOK {
		t.Fatalf("healthz while draining: %d", rec.Code)
	}
}

func TestChatRejectsNewStreamsWhileDraining(t *testing.T) {
	deps := mockDeps()
	deps.Drain = NewDrainer()
	deps.Drain.StartDrain()
	srv := New(testCfg(), discardLogger(), deps)
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, httptest.NewRequest(http.MethodPost, "/api/v1/chat/stream",
		strings.NewReader(`{"workspace_id":"ws1","message":"hi"}`)))
	if rec.Code != http.StatusServiceUnavailable || rec.Header().Get("Retry-After") == "" {
		t.Fatalf("expected 503 + Retry-After, got %d (Retry-After=%q)", rec.Code, rec.Header().Get("Retry-After"))
	}
	if !strings.Contains(rec.Body.String(), `"draining"`) {
		t.Fatalf("expected the draining error code, got %s", rec.Body.String())
	}
}

// gatedChat streams one delta, then waits for release (or cancellation)
// before finishing — a long-running answer under our control.
type gatedChat struct {
	started chan struct{}
	release chan struct{}
	once    sync.Once
}

func newGatedChat() *gatedChat {
	return &gatedChat{started: make(chan struct{}), release: make(chan struct{})}
}

func (g *gatedChat) Stream(ctx context.Context, _ ports.ChatRequest) (<-chan ports.ChatChunk, error) {
	ch := make(chan ports.ChatChunk)
	go func() {
		defer close(ch)
		select {
		case ch <- ports.ChatChunk{Delta: "partial "}:
		case <-ctx.Done():
			return
		}
		g.once.Do(func() { close(g.started) })
		select {
		case <-g.release:
			select {
			case ch <- ports.ChatChunk{Delta: "complete"}:
			case <-ctx.Done():
				return
			}
			select {
			case ch <- ports.ChatChunk{Done: true}:
			case <-ctx.Done():
			}
		case <-ctx.Done():
		}
	}()
	return ch, nil
}

func runStream(t *testing.T, cfg config.Config, deps Deps) (<-chan *httptest.ResponseRecorder, *http.Server) {
	t.Helper()
	srv := New(cfg, discardLogger(), deps)
	done := make(chan *httptest.ResponseRecorder, 1)
	go func() {
		rec := httptest.NewRecorder()
		srv.Handler.ServeHTTP(rec, httptest.NewRequest(http.MethodPost, "/api/v1/chat/stream",
			strings.NewReader(`{"workspace_id":"ws1","message":"hi"}`)))
		done <- rec
	}()
	return done, srv
}

func TestInFlightStreamFinishesDuringDrain(t *testing.T) {
	for _, unified := range []bool{false, true} {
		chat := newGatedChat()
		d := NewDrainer()
		deps := Deps{RAG: rag.New(mock.QueryEmbedder{Dim: 8}, mock.VectorStore{}), Chat: chat, Drain: d}
		deps = hotPath(deps)
		cfg := testCfg()
		cfg.AgentUnifiedLoop = unified
		done, _ := runStream(t, cfg, deps)
		<-chat.started

		d.StartDrain()
		close(chat.release)
		rec := <-done
		out := rec.Body.String()
		if !strings.Contains(out, "complete") || !strings.Contains(out, "[DONE]") || strings.Contains(out, "event: reconnect") {
			t.Fatalf("unified=%v: in-flight stream should finish normally during drain:\n%s", unified, out)
		}
		if err := d.Wait(context.Background()); err != nil || d.Active() != 0 {
			t.Fatalf("unified=%v: drain should be idle after the stream: %v", unified, err)
		}
	}
}

func TestForcedDrainEndsStreamWithReconnectEvent(t *testing.T) {
	for _, unified := range []bool{false, true} {
		chat := newGatedChat() // never released: the answer outlives the drain window
		d := NewDrainer()
		deps := Deps{RAG: rag.New(mock.QueryEmbedder{Dim: 8}, mock.VectorStore{}), Chat: chat, Drain: d}
		deps = hotPath(deps)
		cfg := testCfg()
		cfg.AgentUnifiedLoop = unified
		done, _ := runStream(t, cfg, deps)
		<-chat.started

		d.StartDrain()
		wctx, cancel := context.WithTimeout(context.Background(), 20*time.Millisecond)
		if err := d.Wait(wctx); err == nil {
			t.Fatalf("unified=%v: expected the drain window to expire", unified)
		}
		cancel()
		d.CancelAll()

		var rec *httptest.ResponseRecorder
		select {
		case rec = <-done:
		case <-time.After(2 * time.Second):
			t.Fatalf("unified=%v: handler did not return after CancelAll", unified)
		}
		out := rec.Body.String()
		iRe := strings.Index(out, "event: reconnect")
		iDone := strings.Index(out, "[DONE]")
		if iRe < 0 || iDone < 0 || iRe > iDone {
			t.Fatalf("unified=%v: expected a reconnect event before [DONE]:\n%s", unified, out)
		}
		if strings.Contains(out, "event: error") {
			t.Fatalf("unified=%v: a drain is not an error; got:\n%s", unified, out)
		}
		if !strings.Contains(out, "partial") {
			t.Fatalf("unified=%v: the partial answer should have streamed:\n%s", unified, out)
		}
	}
}

// During the shutdown delay the replica is already out of rotation (readiness
// 503) but still serves new streams, so requests routed before the endpoint
// removal propagates do not fail.
func TestMarkNotReadyKeepsAcceptingStreams(t *testing.T) {
	d := NewDrainer()
	deps := mockDeps()
	deps.Drain = d
	srv := New(testCfg(), discardLogger(), deps)
	d.MarkNotReady()

	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/readyz", nil))
	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("readyz after MarkNotReady: expected 503, got %d", rec.Code)
	}
	rec = httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, httptest.NewRequest(http.MethodPost, "/api/v1/chat/stream",
		strings.NewReader(`{"workspace_id":"ws1","message":"hi"}`)))
	if rec.Code != http.StatusOK || !strings.Contains(rec.Body.String(), "[DONE]") {
		t.Fatalf("new streams must still be served during the delay, got %d", rec.Code)
	}
}

func TestShutdownSequence(t *testing.T) {
	d := NewDrainer()
	// A straggler that ignores the drain window.
	ctx, release, _ := d.Track(context.Background())
	defer release()

	type phase struct {
		notReady, draining bool
		accepted           bool
	}
	observed := make(chan phase, 1)
	go func() {
		time.Sleep(15 * time.Millisecond) // inside the 60ms delay
		_, rel, ok := d.Track(context.Background())
		rel()
		observed <- phase{notReady: d.NotReady(), draining: d.Draining(), accepted: ok}
	}()

	start := time.Now()
	forced := d.Shutdown(context.Background(), ShutdownPlan{
		Delay: 60 * time.Millisecond, Drain: 40 * time.Millisecond, ForcedGrace: 20 * time.Millisecond,
	}, discardLogger())
	elapsed := time.Since(start)

	p := <-observed
	if !p.notReady || p.draining || !p.accepted {
		t.Fatalf("during the delay: want notReady && !draining && accepting, got %+v", p)
	}
	if !d.Draining() {
		t.Fatal("drain must have started after the delay")
	}
	if _, _, ok := d.Track(context.Background()); ok {
		t.Fatal("new streams must be refused after the delay")
	}
	if forced != 1 || !drainCancelled(ctx) {
		t.Fatalf("straggler should be force-cancelled: forced=%d cause=%v", forced, context.Cause(ctx))
	}
	if elapsed < 100*time.Millisecond || elapsed > 2*time.Second {
		t.Fatalf("sequence took %v, want delay+drain (+grace)", elapsed)
	}
}

func TestShutdownSequenceReturnsEarlyWhenIdle(t *testing.T) {
	d := NewDrainer()
	start := time.Now()
	if forced := d.Shutdown(context.Background(), ShutdownPlan{Drain: 5 * time.Second}, discardLogger()); forced != 0 {
		t.Fatalf("idle drain forced %d streams", forced)
	}
	if time.Since(start) > time.Second {
		t.Fatal("an idle replica must not wait out the drain window")
	}
}
