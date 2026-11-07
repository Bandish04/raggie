// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"net/netip"
	"strings"
	"testing"
	"time"

	"github.com/alicangunduz/raggie/services/edge/internal/config"
	"github.com/alicangunduz/raggie/services/edge/internal/ratelimit"
	"github.com/alicangunduz/raggie/services/edge/internal/widgetauth"
)

// downLimiter simulates Redis being unreachable.
type downLimiter struct{ calls int }

func (d *downLimiter) Allow(context.Context, string, int, time.Duration) (ratelimit.Decision, error) {
	d.calls++
	return ratelimit.Decision{Allowed: true}, errors.New("redis: connection refused")
}

func limitedCfg() config.Config {
	cfg := widgetCfg()
	cfg.RateLimitChatUserPerMinute = 2
	cfg.RateLimitChatWidgetSessionPerMinute = 2
	cfg.RateLimitChatWidgetIPPerMinute = 3
	cfg.RateLimitWidgetTokenPerMinute = 2
	return cfg
}

func serve(srv *http.Server, req *http.Request) *httptest.ResponseRecorder {
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)
	return rec
}

func assert429(t *testing.T, rec *httptest.ResponseRecorder) {
	t.Helper()
	if rec.Code != http.StatusTooManyRequests {
		t.Fatalf("expected 429, got %d (%s)", rec.Code, rec.Body.String())
	}
	if ra := rec.Header().Get("Retry-After"); ra == "" || ra == "0" {
		t.Fatalf("expected a positive Retry-After header, got %q", ra)
	}
}

func TestChatRateLimitedPerUser(t *testing.T) {
	deps := mockDeps()
	deps.WSInfo = fakeWS{typ: "INTERNAL", access: true}
	deps.RateLimiter = ratelimit.NewMemory(time.Now)
	srv := newSrvWithCfg(t, limitedCfg(), deps)

	chat := func(sub string) *httptest.ResponseRecorder {
		req := httptest.NewRequest(http.MethodPost, "/api/v1/chat/stream",
			strings.NewReader(`{"workspace_id":"wsX","message":"hi"}`))
		req.Header.Set("Authorization", "Bearer "+adminToken(t, "STAFF", sub))
		return serve(srv, req)
	}
	for i := 0; i < 2; i++ {
		if rec := chat("u1"); rec.Code != http.StatusOK {
			t.Fatalf("request %d: expected 200, got %d", i+1, rec.Code)
		}
	}
	rec := chat("u1")
	assert429(t, rec)
	if !strings.Contains(rec.Body.String(), `"rate_limited"`) {
		t.Fatalf("expected the rate_limited error code, got %s", rec.Body.String())
	}
	if rec := chat("u2"); rec.Code != http.StatusOK {
		t.Fatalf("another user must not share the bucket, got %d", rec.Code)
	}
}

func widgetChat(t *testing.T, srv *http.Server, tok, ip string) *httptest.ResponseRecorder {
	req := httptest.NewRequest(http.MethodPost, "/api/v1/chat/stream",
		strings.NewReader(`{"workspace_id":"wsX","message":"hi"}`))
	req.Header.Set("Origin", "https://acme.example")
	req.Header.Set("Authorization", "Bearer "+tok)
	req.RemoteAddr = ip + ":40000"
	return serve(srv, req)
}

func TestChatRateLimitedPerWidgetSession(t *testing.T) {
	deps := mockDeps()
	deps.WSInfo = fakeWS{typ: "EXTERNAL", cors: []string{"https://acme.example"}}
	deps.RateLimiter = ratelimit.NewMemory(time.Now)
	srv := newSrvWithCfg(t, limitedCfg(), deps)

	tokA, _ := widgetauth.Mint("test-secret", "wsX", 30*time.Minute, time.Now())
	tokB, _ := widgetauth.Mint("test-secret", "wsX", 30*time.Minute, time.Now())
	// Session A from two different IPs still shares its session bucket.
	if rec := widgetChat(t, srv, tokA, "203.0.113.1"); rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rec.Code)
	}
	if rec := widgetChat(t, srv, tokA, "203.0.113.2"); rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rec.Code)
	}
	assert429(t, widgetChat(t, srv, tokA, "203.0.113.3"))
	// A fresh session is unaffected.
	if rec := widgetChat(t, srv, tokB, "203.0.113.4"); rec.Code != http.StatusOK {
		t.Fatalf("fresh session must pass, got %d", rec.Code)
	}
}

func TestChatRateLimitedPerWidgetIP(t *testing.T) {
	deps := mockDeps()
	deps.WSInfo = fakeWS{typ: "EXTERNAL", cors: []string{"https://acme.example"}}
	deps.RateLimiter = ratelimit.NewMemory(time.Now)
	srv := newSrvWithCfg(t, limitedCfg(), deps)

	// Rotating tokens (new session each time) from ONE IP hits the IP bucket.
	for i := 0; i < 3; i++ {
		tok, _ := widgetauth.Mint("test-secret", "wsX", 30*time.Minute, time.Now())
		if rec := widgetChat(t, srv, tok, "198.51.100.7"); rec.Code != http.StatusOK {
			t.Fatalf("request %d: expected 200, got %d", i+1, rec.Code)
		}
	}
	tok, _ := widgetauth.Mint("test-secret", "wsX", 30*time.Minute, time.Now())
	assert429(t, widgetChat(t, srv, tok, "198.51.100.7"))
}

func TestWidgetTokenRateLimitedPerIPAndWorkspace(t *testing.T) {
	deps := mockDeps()
	deps.WSInfo = fakeWS{typ: "EXTERNAL", cors: []string{"https://acme.example"}}
	deps.RateLimiter = ratelimit.NewMemory(time.Now)
	srv := newSrvWithCfg(t, limitedCfg(), deps)

	issue := func(ws, ip string) *httptest.ResponseRecorder {
		req := httptest.NewRequest(http.MethodPost, "/api/v1/widget/token",
			strings.NewReader(`{"workspace_id":"`+ws+`"}`))
		req.Header.Set("Origin", "https://acme.example")
		req.RemoteAddr = ip + ":5555"
		return serve(srv, req)
	}
	for i := 0; i < 2; i++ {
		if rec := issue(widgetWS, "192.0.2.10"); rec.Code != http.StatusOK {
			t.Fatalf("request %d: expected 200, got %d", i+1, rec.Code)
		}
	}
	assert429(t, issue(widgetWS, "192.0.2.10"))
	if rec := issue(widgetWS2, "192.0.2.10"); rec.Code != http.StatusOK {
		t.Fatalf("other workspace must have its own bucket, got %d", rec.Code)
	}
	if rec := issue(widgetWS, "192.0.2.11"); rec.Code != http.StatusOK {
		t.Fatalf("other IP must have its own bucket, got %d", rec.Code)
	}
}

// Redis outage: requests are admitted (fail-open) and the limiter was consulted.
func TestRateLimitFailsOpenWhenBackendDown(t *testing.T) {
	deps := mockDeps()
	deps.WSInfo = fakeWS{typ: "INTERNAL", access: true}
	down := &downLimiter{}
	deps.RateLimiter = down
	srv := newSrvWithCfg(t, limitedCfg(), deps)
	for i := 0; i < 5; i++ {
		req := httptest.NewRequest(http.MethodPost, "/api/v1/chat/stream",
			strings.NewReader(`{"workspace_id":"wsX","message":"hi"}`))
		req.Header.Set("Authorization", "Bearer "+adminToken(t, "STAFF", "u1"))
		if rec := serve(srv, req); rec.Code != http.StatusOK {
			t.Fatalf("fail-open expected 200, got %d", rec.Code)
		}
	}
	if down.calls == 0 {
		t.Fatal("limiter was never consulted")
	}
}

func TestClientIP(t *testing.T) {
	trusted := []netip.Prefix{netip.MustParsePrefix("10.0.0.0/8")}
	cases := []struct {
		name, remote, xff string
		trusted           []netip.Prefix
		want              string
	}{
		{"direct client, XFF ignored", "203.0.113.9:1234", "1.2.3.4", nil, "203.0.113.9"},
		{"untrusted peer cannot spoof", "203.0.113.9:1234", "1.2.3.4", trusted, "203.0.113.9"},
		{"trusted proxy", "10.1.2.3:80", "198.51.100.1", trusted, "198.51.100.1"},
		{"rightmost untrusted hop wins", "10.1.2.3:80", "6.6.6.6, 198.51.100.1, 10.9.9.9", trusted, "198.51.100.1"},
		{"all hops trusted", "10.1.2.3:80", "10.4.4.4", trusted, "10.4.4.4"},
		{"garbage XFF falls back to peer", "10.1.2.3:80", "not-an-ip", trusted, "10.1.2.3"},
		{"ipv6 peer", "[2001:db8::1]:443", "", nil, "2001:db8::1"},
	}
	for _, tc := range cases {
		req := httptest.NewRequest(http.MethodGet, "/", nil)
		req.RemoteAddr = tc.remote
		if tc.xff != "" {
			req.Header.Set("X-Forwarded-For", tc.xff)
		}
		if got := clientIP(req, tc.trusted); got != tc.want {
			t.Errorf("%s: clientIP=%q want %q", tc.name, got, tc.want)
		}
	}
}
