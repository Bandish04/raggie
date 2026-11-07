// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/alicangunduz/raggie/services/edge/internal/config"
	"github.com/alicangunduz/raggie/services/edge/internal/ports"
)

type readinessStub struct {
	err error
}

func (s readinessStub) Ready(context.Context) error { return s.err }

func newTestServer() *http.Server {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	return New(config.Config{Port: "8080", LogLevel: "error"}, logger, Deps{})
}

func TestHealthz(t *testing.T) {
	srv := newTestServer()
	req := httptest.NewRequest(http.MethodGet, "/healthz", nil)
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("GET /healthz: expected 200, got %d", rec.Code)
	}
	if got := rec.Header().Get("X-Request-Id"); got == "" {
		t.Fatal("expected X-Request-Id header to be set by middleware")
	}
}

func TestReadyz(t *testing.T) {
	srv := newTestServer()
	req := httptest.NewRequest(http.MethodGet, "/readyz", nil)
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("GET /readyz: expected 200, got %d", rec.Code)
	}
}

func TestReadyzReportsFailedDependencyWithoutLeakingError(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	srv := New(
		config.Config{Port: "8080", LogLevel: "error", ReadinessTimeoutSeconds: 1},
		logger,
		Deps{Readiness: []ReadinessCheck{
			{Name: "qdrant", Probe: readinessStub{}, Required: true},
			{Name: "llm", Probe: readinessStub{err: errors.New("secret upstream detail")}, Required: true},
		}},
	)
	req := httptest.NewRequest(http.MethodGet, "/readyz", nil)
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("GET /readyz: expected 503, got %d", rec.Code)
	}
	body := rec.Body.String()
	if !strings.Contains(body, `"llm":"unavailable"`) || !strings.Contains(body, `"qdrant":"ok"`) {
		t.Fatalf("unexpected readiness body: %s", body)
	}
	if strings.Contains(body, "secret upstream detail") {
		t.Fatalf("readiness response leaked internal error: %s", body)
	}
}

func TestReadyzReportsOptionalDependencyAsDegraded(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	srv := New(
		config.Config{Port: "8080", LogLevel: "error", ReadinessTimeoutSeconds: 1},
		logger,
		Deps{Readiness: []ReadinessCheck{
			{Name: "qdrant", Probe: readinessStub{}, Required: true},
			{Name: "redis", Probe: readinessStub{err: errors.New("down")}},
		}},
	)
	req := httptest.NewRequest(http.MethodGet, "/readyz", nil)
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("GET /readyz: expected 200 for optional dependency failure, got %d", rec.Code)
	}
	if body := rec.Body.String(); !strings.Contains(body, `"status":"degraded"`) {
		t.Fatalf("unexpected readiness body: %s", body)
	}
}

func TestMetrics(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	srv := NewMetricsServer(config.Config{MetricsAddr: "127.0.0.1:9090"}, logger, Deps{})
	if srv.Addr != "127.0.0.1:9090" {
		t.Fatalf("metrics addr = %q", srv.Addr)
	}
	req := httptest.NewRequest(http.MethodGet, "/metrics", nil)
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK || !strings.Contains(rec.Body.String(), "raggie_edge_up 1") {
		t.Fatalf("GET /metrics: expected 200 with exposition, got %d", rec.Code)
	}
}

// /metrics is internal-only: never served on the public listener.
func TestMetricsNotServedOnPublicListener(t *testing.T) {
	srv := newTestServer()
	req := httptest.NewRequest(http.MethodGet, "/metrics", nil)
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusNotFound {
		t.Fatalf("public GET /metrics: expected 404, got %d", rec.Code)
	}
}

func TestMetricsTokenRequiredWhenConfigured(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	srv := NewMetricsServer(config.Config{MetricsAddr: ":9090", MetricsToken: "m-token"}, logger, Deps{})
	for _, tc := range []struct {
		auth string
		want int
	}{
		{"", http.StatusUnauthorized},
		{"Bearer wrong", http.StatusUnauthorized},
		{"Bearer m-token", http.StatusOK},
	} {
		req := httptest.NewRequest(http.MethodGet, "/metrics", nil)
		if tc.auth != "" {
			req.Header.Set("Authorization", tc.auth)
		}
		rec := httptest.NewRecorder()
		srv.Handler.ServeHTTP(rec, req)
		if rec.Code != tc.want {
			t.Fatalf("auth %q: expected %d, got %d", tc.auth, tc.want, rec.Code)
		}
	}
}

type countingReranker struct{ failOpen int64 }

func (countingReranker) Rerank(context.Context, string, []string, int) ([]ports.RerankHit, error) {
	return nil, nil
}
func (r countingReranker) FailOpenTotal() int64 { return r.failOpen }

func TestMetricsExposeRerankFailOpenCounter(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	srv := NewMetricsServer(config.Config{}, logger, Deps{WebReranker: countingReranker{failOpen: 7}})
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/metrics", nil))

	body := rec.Body.String()
	for _, want := range []string{
		"# TYPE raggie_edge_rerank_fail_open_total counter\n",
		"raggie_edge_rerank_fail_open_total 7\n",
	} {
		if !strings.Contains(body, want) {
			t.Fatalf("metrics missing %q:\n%s", want, body)
		}
	}
}
