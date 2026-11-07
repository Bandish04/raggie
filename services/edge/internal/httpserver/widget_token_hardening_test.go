// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"bufio"
	"context"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/alicangunduz/raggie/services/edge/internal/ports"
	"github.com/alicangunduz/raggie/services/edge/internal/ratelimit"
)

const (
	widgetWS  = "0b6f2c1e-7a3d-4c5e-9f10-2a3b4c5d6e7f"
	widgetWS2 = "1c7a3d2f-8b4e-4d6f-a021-3b4c5d6e7f80"
	widgetWS3 = "2d8b4e3a-9c5f-4e7a-b132-4c5d6e7f8091"
)

// countingWS records workspace lookups (the database round trip).
type countingWS struct {
	fakeWS
	lookups atomic.Int32
}

func (c *countingWS) WorkspaceWidget(ctx context.Context, id string) (string, []string, string, string, error) {
	c.lookups.Add(1)
	return c.fakeWS.WorkspaceWidget(ctx, id)
}

func issueWidgetToken(srv *http.Server, ws, ip string) *httptest.ResponseRecorder {
	req := httptest.NewRequest(http.MethodPost, "/api/v1/widget/token", strings.NewReader(`{"workspace_id":"`+ws+`"}`))
	req.Header.Set("Origin", "https://acme.example")
	req.RemoteAddr = ip + ":5555"
	return serve(srv, req)
}

// A workspace id that is not a UUID is refused before it costs a database
// lookup (or a rate-limit bucket keyed on attacker-chosen text).
func TestWidgetTokenRejectsNonUUIDWorkspaceBeforeLookup(t *testing.T) {
	ws := &countingWS{fakeWS: fakeWS{typ: "EXTERNAL", cors: []string{"https://acme.example"}}}
	deps := mockDeps()
	deps.WSInfo = ws
	srv := newSrv(t, deps)
	for _, id := range []string{"wsX", "1 OR 1=1", strings.Repeat("a", 200), widgetWS + "x"} {
		if rec := issueWidgetToken(srv, id, "192.0.2.1"); rec.Code != http.StatusBadRequest {
			t.Fatalf("workspace_id %q: status %d, want 400", id, rec.Code)
		}
	}
	if n := ws.lookups.Load(); n != 0 {
		t.Fatalf("%d workspace lookup(s) for invalid ids", n)
	}
	if rec := issueWidgetToken(srv, widgetWS, "192.0.2.1"); rec.Code != http.StatusOK {
		t.Fatalf("valid UUID: status %d", rec.Code)
	}
}

// Rotating the client-chosen workspace_id must not escape the issuance limit:
// an IP-only bucket caps every workspace together.
func TestWidgetTokenIPBucketSpansWorkspaces(t *testing.T) {
	deps := mockDeps()
	deps.WSInfo = fakeWS{typ: "EXTERNAL", cors: []string{"https://acme.example"}}
	deps.RateLimiter = ratelimit.NewMemory(time.Now)
	cfg := limitedCfg()
	cfg.RateLimitWidgetTokenPerMinute = 100
	cfg.RateLimitWidgetTokenIPPerMinute = 2
	srv := newSrvWithCfg(t, cfg, deps)

	if rec := issueWidgetToken(srv, widgetWS, "192.0.2.20"); rec.Code != http.StatusOK {
		t.Fatalf("first: %d", rec.Code)
	}
	if rec := issueWidgetToken(srv, widgetWS2, "192.0.2.20"); rec.Code != http.StatusOK {
		t.Fatalf("second (other workspace): %d", rec.Code)
	}
	assert429(t, issueWidgetToken(srv, widgetWS3, "192.0.2.20"))
	if rec := issueWidgetToken(srv, widgetWS3, "192.0.2.21"); rec.Code != http.StatusOK {
		t.Fatalf("another IP has its own bucket: %d", rec.Code)
	}
}

// A client that sends headers and then trickles the body is cut off by the
// body read deadline instead of holding the connection open.
func TestSlowRequestBodyHitsReadDeadline(t *testing.T) {
	deps := mockDeps()
	deps.WSInfo = fakeWS{typ: "EXTERNAL", cors: []string{"https://acme.example"}}
	cfg := widgetCfg()
	cfg.HTTPBodyReadTimeoutSeconds = 1
	ts := httptest.NewServer(New(cfg, discardLogger(), deps).Handler)
	defer ts.Close()

	conn, err := net.Dial("tcp", ts.Listener.Addr().String())
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	fmt.Fprintf(conn, "POST /api/v1/widget/token HTTP/1.1\r\nHost: x\r\nOrigin: https://acme.example\r\n"+
		"Content-Type: application/json\r\nContent-Length: 64\r\n\r\n{\"workspace")
	_ = conn.SetReadDeadline(time.Now().Add(5 * time.Second))
	start := time.Now()
	resp, err := http.ReadResponse(bufio.NewReader(conn), nil)
	if err == nil {
		_ = resp.Body.Close()
		if resp.StatusCode != http.StatusBadRequest {
			t.Fatalf("slow body: status %d, want 400", resp.StatusCode)
		}
	} else if ne, ok := err.(net.Error); ok && ne.Timeout() {
		t.Fatal("the server never gave up on the stalled body")
	}
	if waited := time.Since(start); waited > 4*time.Second {
		t.Fatalf("slow body held the connection for %s", waited)
	}
}

// slowChat streams for longer than the body read deadline.
type slowChat struct{ delay time.Duration }

func (c slowChat) Stream(ctx context.Context, _ ports.ChatRequest) (<-chan ports.ChatChunk, error) {
	ch := make(chan ports.ChatChunk, 2)
	go func() {
		defer close(ch)
		select {
		case <-time.After(c.delay):
		case <-ctx.Done():
			return
		}
		ch <- ports.ChatChunk{Delta: "late but complete"}
		ch <- ports.ChatChunk{Done: true, FinishReason: "stop"}
	}()
	return ch, nil
}

// The body deadline covers reading the request only: an SSE answer that takes
// longer than it streams to the end.
func TestBodyReadDeadlineDoesNotCutTheStream(t *testing.T) {
	deps := memoryDeps(&fakeMemory{}, &memoryChat{}, memoryCase{})
	deps.Memory = nil
	deps.Chat = slowChat{delay: 1500 * time.Millisecond}
	cfg := widgetCfg()
	cfg.HTTPBodyReadTimeoutSeconds = 1
	ts := httptest.NewServer(New(cfg, discardLogger(), deps).Handler)
	defer ts.Close()

	req, _ := http.NewRequest(http.MethodPost, ts.URL+"/api/v1/chat/stream",
		strings.NewReader(`{"workspace_id":"ws1","message":"What is the capital of France?"}`))
	req.Header.Set("Authorization", "Bearer "+adminToken(t, "SUPER_ADMIN", "user-1"))
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		t.Fatalf("stream cut: %v (got %q)", err, body)
	}
	if resp.StatusCode != http.StatusOK || !strings.Contains(string(body), "late but complete") || !strings.Contains(string(body), "[DONE]") {
		t.Fatalf("stream incomplete: %d %q", resp.StatusCode, body)
	}
}

// deadlineWriter records the read deadlines http.ResponseController sets.
type deadlineWriter struct {
	httptest.ResponseRecorder
	deadlines []time.Time
}

func (d *deadlineWriter) SetReadDeadline(t time.Time) error {
	d.deadlines = append(d.deadlines, t)
	return nil
}

// The deadline is armed for the body and cleared after a successful decode
// (a stale one would cancel a later SSE stream once net/http reads to EOF); a
// failed decode keeps it, so draining the unread body gives up as well.
func TestDecodeJSONBodyReadDeadline(t *testing.T) {
	decode := func(body string) (*deadlineWriter, error) {
		w := &deadlineWriter{ResponseRecorder: *httptest.NewRecorder()}
		r := httptest.NewRequest(http.MethodPost, "/", strings.NewReader(body))
		r = r.WithContext(context.WithValue(r.Context(), bodyReadTimeoutKey{}, 2*time.Second))
		var v map[string]any
		return w, decodeJSONBody(w, r, 1<<10, &v)
	}
	w, err := decode(`{"a":1}`)
	if err != nil || len(w.deadlines) != 2 || w.deadlines[0].IsZero() || !w.deadlines[1].IsZero() {
		t.Fatalf("success: err=%v deadlines=%v; want armed then cleared", err, w.deadlines)
	}
	w, err = decode(`{"a":`)
	if err == nil || len(w.deadlines) != 1 || w.deadlines[0].IsZero() {
		t.Fatalf("failure: err=%v deadlines=%v; want armed and kept", err, w.deadlines)
	}
}
