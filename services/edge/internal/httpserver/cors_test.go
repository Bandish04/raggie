// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/alicangunduz/raggie/services/edge/internal/ratelimit"
	"github.com/alicangunduz/raggie/services/edge/internal/widgetauth"
)

func assertCORSExposed(t *testing.T, rec *httptest.ResponseRecorder, origin string) {
	t.Helper()
	if got := rec.Header().Get("Access-Control-Allow-Origin"); got != origin {
		t.Fatalf("status %d: Access-Control-Allow-Origin = %q, want %q", rec.Code, got, origin)
	}
	exposed := strings.ToLower(rec.Header().Get("Access-Control-Expose-Headers"))
	for _, h := range []string{"retry-after", "x-request-id"} {
		if !strings.Contains(exposed, h) {
			t.Fatalf("status %d: %s not exposed (Access-Control-Expose-Headers=%q)", rec.Code, h, exposed)
		}
	}
}

func widgetChatReq(tok string) *http.Request {
	req := httptest.NewRequest(http.MethodPost, "/api/v1/chat/stream", strings.NewReader(`{"workspace_id":"wsX","message":"hi"}`))
	req.Header.Set("Origin", "https://acme.example")
	if tok != "" {
		req.Header.Set("Authorization", "Bearer "+tok)
	}
	req.RemoteAddr = "203.0.113.50:1000"
	return req
}

// The widget is cross-origin: every widget-facing response, including 401,
// 429 and 503, must let its script read the status and Retry-After.
func TestWidgetResponsesExposeRetryAfter(t *testing.T) {
	deps := mockDeps()
	deps.WSInfo = fakeWS{typ: "EXTERNAL", cors: []string{"https://acme.example"}}
	deps.RateLimiter = ratelimit.NewMemory(time.Now)
	cfg := widgetCfg()
	cfg.RateLimitChatWidgetSessionPerMinute = 1
	cfg.RateLimitWidgetTokenPerMinute = 1
	srv := newSrvWithCfg(t, cfg, deps)
	tok, _ := widgetauth.Mint("test-secret", "wsX", 30*time.Minute, time.Now())

	for _, tc := range []struct {
		name string
		req  *http.Request
		want int
	}{
		{"chat 200", widgetChatReq(tok), http.StatusOK},
		{"chat 429", widgetChatReq(tok), http.StatusTooManyRequests},
		{"chat 401 bad token", widgetChatReq("bogus"), http.StatusUnauthorized},
	} {
		rec := httptest.NewRecorder()
		srv.Handler.ServeHTTP(rec, tc.req)
		if rec.Code != tc.want {
			t.Fatalf("%s: status %d, want %d", tc.name, rec.Code, tc.want)
		}
		assertCORSExposed(t, rec, "https://acme.example")
	}

	token := func() *httptest.ResponseRecorder {
		req := httptest.NewRequest(http.MethodPost, "/api/v1/widget/token", strings.NewReader(`{"workspace_id":"`+widgetWS+`"}`))
		req.Header.Set("Origin", "https://acme.example")
		req.RemoteAddr = "203.0.113.60:1000"
		rec := httptest.NewRecorder()
		srv.Handler.ServeHTTP(rec, req)
		return rec
	}
	if rec := token(); rec.Code != http.StatusOK {
		t.Fatalf("token: %d", rec.Code)
	} else {
		assertCORSExposed(t, rec, "https://acme.example")
	}
	rec := token()
	if rec.Code != http.StatusTooManyRequests || rec.Header().Get("Retry-After") == "" {
		t.Fatalf("token 429 expected with Retry-After, got %d", rec.Code)
	}
	assertCORSExposed(t, rec, "https://acme.example")
}

func TestDrainingChatExposesRetryAfterCrossOrigin(t *testing.T) {
	deps := mockDeps()
	deps.Drain = NewDrainer()
	deps.Drain.StartDrain()
	srv := New(testCfg(), discardLogger(), deps)
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, widgetChatReq("x"))
	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("expected 503, got %d", rec.Code)
	}
	assertCORSExposed(t, rec, "https://acme.example")
}

// The widget's chat POST carries Authorization + JSON, so browsers preflight
// it; without an OPTIONS route the cross-origin widget cannot chat at all.
func TestChatStreamPreflight(t *testing.T) {
	srv := newSrv(t, mockDeps())
	req := httptest.NewRequest(http.MethodOptions, "/api/v1/chat/stream", nil)
	req.Header.Set("Origin", "https://acme.example")
	req.Header.Set("Access-Control-Request-Method", "POST")
	req.Header.Set("Access-Control-Request-Headers", "authorization,content-type")
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusNoContent {
		t.Fatalf("preflight status %d", rec.Code)
	}
	h := rec.Header()
	if h.Get("Access-Control-Allow-Origin") != "https://acme.example" ||
		!strings.Contains(h.Get("Access-Control-Allow-Methods"), "POST") ||
		!strings.Contains(strings.ToLower(h.Get("Access-Control-Allow-Headers")), "authorization") {
		t.Fatalf("preflight headers: %v", h)
	}
}
