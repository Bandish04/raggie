// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/alicangunduz/raggie/services/edge/internal/config"
	"github.com/alicangunduz/raggie/services/edge/internal/ports/mock"
	"github.com/alicangunduz/raggie/services/edge/internal/rag"
)

func TestChatRejectsOversizedBody(t *testing.T) {
	cfg := testCfg()
	cfg.ChatMaxBodyBytes = 4096
	srv := New(cfg, discardLogger(), mockDeps())

	body := `{"workspace_id":"ws1","message":"` + strings.Repeat("a", 8192) + `"}`
	req := httptest.NewRequest(http.MethodPost, "/api/v1/chat/stream", strings.NewReader(body))
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusRequestEntityTooLarge {
		t.Fatalf("expected 413 for an oversized chat body, got %d (%s)", rec.Code, rec.Body.String())
	}
	if !strings.Contains(rec.Body.String(), `"payload_too_large"`) {
		t.Fatalf("expected the payload_too_large error code, got %s", rec.Body.String())
	}
}

func TestChatAcceptsBodyWithinLimit(t *testing.T) {
	cfg := testCfg()
	cfg.ChatMaxBodyBytes = 4096
	srv := New(cfg, discardLogger(), mockDeps())
	req := httptest.NewRequest(http.MethodPost, "/api/v1/chat/stream",
		strings.NewReader(`{"workspace_id":"ws1","message":"hi"}`))
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rec.Code)
	}
}

func TestWidgetTokenRejectsOversizedBody(t *testing.T) {
	deps := mockDeps()
	deps.WSInfo = fakeWS{typ: "EXTERNAL", cors: []string{"https://acme.example"}}
	srv := newSrv(t, deps)
	body := `{"workspace_id":"wsX","pad":"` + strings.Repeat("a", 64<<10) + `"}`
	req := httptest.NewRequest(http.MethodPost, "/api/v1/widget/token", strings.NewReader(body))
	req.Header.Set("Origin", "https://acme.example")
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusRequestEntityTooLarge {
		t.Fatalf("expected 413 for an oversized widget-token body, got %d", rec.Code)
	}
}

func TestDecodeJSONBodyLimits(t *testing.T) {
	var v struct {
		A string `json:"a"`
	}
	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/", strings.NewReader(`{"a":"`+strings.Repeat("x", 100)+`"}`))
	if err := decodeJSONBody(rec, req, 16, &v); err != errBodyTooLarge {
		t.Fatalf("expected errBodyTooLarge, got %v", err)
	}
	req = httptest.NewRequest(http.MethodPost, "/", strings.NewReader(`{"a":"ok"}`))
	if err := decodeJSONBody(rec, req, 1024, &v); err != nil || v.A != "ok" {
		t.Fatalf("decode within limit: v=%+v err=%v", v, err)
	}
	req = httptest.NewRequest(http.MethodPost, "/", strings.NewReader(`not json`))
	if err := decodeJSONBody(rec, req, 1024, &v); err == nil || err == errBodyTooLarge {
		t.Fatalf("expected a plain decode error, got %v", err)
	}
}

// Server-level timeouts: slow-header (slowloris) protection and idle keep-alive
// reaping are on; WriteTimeout stays 0 because SSE streams are long-lived.
func TestServerTimeouts(t *testing.T) {
	srv := New(config.Config{Port: "8080"}, discardLogger(), Deps{})
	if srv.ReadHeaderTimeout <= 0 || srv.ReadHeaderTimeout > 30*time.Second {
		t.Fatalf("ReadHeaderTimeout = %v", srv.ReadHeaderTimeout)
	}
	if srv.IdleTimeout <= 0 {
		t.Fatalf("IdleTimeout must be set, got %v", srv.IdleTimeout)
	}
	if srv.WriteTimeout != 0 {
		t.Fatalf("WriteTimeout must stay 0 for SSE, got %v", srv.WriteTimeout)
	}
	if srv.MaxHeaderBytes <= 0 || srv.MaxHeaderBytes > 1<<20 {
		t.Fatalf("MaxHeaderBytes = %d", srv.MaxHeaderBytes)
	}
}

// Each requested workspace costs an authorization query, so the "all
// workspaces" set is bounded.
func TestChatRejectsTooManyWorkspaceIDs(t *testing.T) {
	srv := New(testCfg(), discardLogger(), mockDeps())
	ids := make([]string, maxWorkspaceIDs+1)
	for i := range ids {
		ids[i] = `"ws` + strings.Repeat("x", 3) + `"`
	}
	body := `{"workspace_id":"ws1","workspace_ids":[` + strings.Join(ids, ",") + `],"message":"hi"}`
	req := httptest.NewRequest(http.MethodPost, "/api/v1/chat/stream", strings.NewReader(body))
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected 400 for %d workspace ids, got %d", len(ids), rec.Code)
	}
}

// Each small JSON endpoint caps its body and answers 413 above the cap. The
// bodies are valid JSON, so without the cap they would decode and get some
// other status (400 for a too-long description, 200 for a parsed schedule).
func TestSmallJSONEndpointsRejectOversizedBodies(t *testing.T) {
	pad := strings.Repeat("a", 2<<20) // above every cap (the largest is 1 MiB)
	cfg := widgetCfg()
	cfg.InternalAPISecret = "internal-secret-0123456789abcdef"
	cfg.RetrieveCandidateK, cfg.RetrieveContextK = 4, 2
	deps := hotPath(Deps{
		RAG:    rag.New(mock.QueryEmbedder{Dim: 8}, mock.VectorStore{}),
		Chat:   mock.ChatProvider{Response: `{"cron":"0 9 * * *","prompt":"p","name":"n","summary":"s"}`},
		WSInfo: fakeWS{typ: "INTERNAL", access: true},
	})
	srv := New(cfg, discardLogger(), deps)
	for _, tc := range []struct {
		name, path, body, header, value string
	}{
		{"skill instructions", "/api/v1/skills/generate-instructions", `{"description":"` + pad + `"}`,
			"Authorization", "Bearer " + adminToken(t, "STAFF", "u1")},
		{"schedule parse", "/api/v1/schedule/parse", `{"text":"` + pad + `"}`,
			"Authorization", "Bearer " + adminToken(t, "STAFF", "u1")},
		{"run task", "/api/v1/internal/run-task", `{"workspace_id":"w1","user_id":"u1","prompt":"` + pad + `"}`,
			"X-Internal-Secret", cfg.InternalAPISecret},
	} {
		t.Run(tc.name, func(t *testing.T) {
			req := httptest.NewRequest(http.MethodPost, tc.path, strings.NewReader(tc.body))
			req.Header.Set(tc.header, tc.value)
			rec := httptest.NewRecorder()
			srv.Handler.ServeHTTP(rec, req)
			if rec.Code != http.StatusRequestEntityTooLarge || !strings.Contains(rec.Body.String(), `"payload_too_large"`) {
				t.Fatalf("expected 413 payload_too_large, got %d (%.200s)", rec.Code, rec.Body.String())
			}
		})
	}
}

// Message feedback needs the conversation store, so this one runs against
// Postgres (skipped without DATABASE_URL).
func TestMessageFeedbackRejectsOversizedBody(t *testing.T) {
	f := newMatrixFixture(t)
	srv := New(f.cfg, discardLogger(), f.deps)
	_, botMsg := f.seedConversation(t, f.wsAInternal, f.users[pStaffMember], "rate me")
	body := `{"rating":"up","pad":"` + strings.Repeat("a", 2*smallJSONBodyBytes) + `"}`
	req := jsonReq(http.MethodPost, "/api/v1/messages/"+botMsg+"/feedback", body)
	for k, v := range f.headers[pStaffMember] {
		req.Header.Set(k, v)
	}
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusRequestEntityTooLarge {
		t.Fatalf("expected 413 for an oversized feedback body, got %d (%s)", rec.Code, rec.Body.String())
	}
}
