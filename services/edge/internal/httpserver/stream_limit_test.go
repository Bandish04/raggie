// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestStreamLimiterAdmitsUpToTheCap(t *testing.T) {
	l := NewStreamLimiter(2)
	r1, ok1 := l.Acquire()
	_, ok2 := l.Acquire()
	if !ok1 || !ok2 {
		t.Fatal("streams below the cap must be admitted")
	}
	if _, ok := l.Acquire(); ok {
		t.Fatal("a stream above the cap must be refused")
	}
	if open, limit, rejected := l.Stats(); open != 2 || limit != 2 || rejected != 1 {
		t.Fatalf("stats = open %d, limit %d, rejected %d; want 2, 2, 1", open, limit, rejected)
	}
	r1()
	r1() // release is idempotent
	if _, ok := l.Acquire(); !ok {
		t.Fatal("a released slot must be reusable")
	}
	if open, _, _ := l.Stats(); open != 2 {
		t.Fatalf("open = %d after release + acquire, want 2", open)
	}

	unlimited := NewStreamLimiter(0)
	for i := 0; i < 1000; i++ {
		if _, ok := unlimited.Acquire(); !ok {
			t.Fatal("0 means unlimited")
		}
	}
	var none *StreamLimiter
	if release, ok := none.Acquire(); !ok {
		t.Fatal("a nil limiter means unlimited")
	} else {
		release()
	}
}

// At the cap a new chat gets 503 busy with Retry-After before any SSE byte;
// below the cap it streams normally.
func TestChatStreamCapShedsBeforeTheStream(t *testing.T) {
	newServer := func(l *StreamLimiter) http.Handler {
		deps := memoryDeps(&fakeMemory{}, &memoryChat{}, memoryCase{})
		deps.Memory = nil
		deps.Streams = l
		return New(widgetCfg(), discardLogger(), deps).Handler
	}

	below := NewStreamLimiter(2)
	held, _ := below.Acquire() // one stream already open; one slot left
	defer held()
	rec := httptest.NewRecorder()
	newServer(below).ServeHTTP(rec, memoryChatRequest(t, memoryCase{}))
	if rec.Code != http.StatusOK || !strings.Contains(rec.Body.String(), "[DONE]") {
		t.Fatalf("below cap: %d %s", rec.Code, rec.Body.String())
	}
	if open, _, _ := below.Stats(); open != 1 {
		t.Fatalf("finished stream did not release its slot: open = %d", open)
	}

	full := NewStreamLimiter(1)
	held2, _ := full.Acquire()
	defer held2()
	rec = httptest.NewRecorder()
	newServer(full).ServeHTTP(rec, memoryChatRequest(t, memoryCase{}))
	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("at cap: status %d, want 503: %s", rec.Code, rec.Body.String())
	}
	if rec.Header().Get("Retry-After") == "" || !strings.Contains(rec.Body.String(), `"busy"`) {
		t.Fatalf("at cap: want a retryable busy error, got headers %v body %s", rec.Header(), rec.Body.String())
	}
	if strings.Contains(rec.Body.String(), "event:") || strings.HasPrefix(rec.Header().Get("Content-Type"), "text/event-stream") {
		t.Fatalf("at cap: an SSE byte was written before shedding: %q", rec.Body.String())
	}
}

func TestMetricsExposeStreamCap(t *testing.T) {
	l := NewStreamLimiter(3)
	l.Acquire()
	rec := httptest.NewRecorder()
	metricsHandler(Deps{Streams: l})(rec, httptest.NewRequest(http.MethodGet, "/metrics", nil))
	for _, want := range []string{"raggie_edge_sse_streams 1\n", "raggie_edge_sse_streams_limit 3\n", "raggie_edge_sse_streams_rejected_total 0\n"} {
		if !strings.Contains(rec.Body.String(), want) {
			t.Fatalf("metrics missing %q", want)
		}
	}
}
