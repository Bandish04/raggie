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
	"time"

	"github.com/alicangunduz/raggie/services/edge/internal/config"
	"github.com/alicangunduz/raggie/services/edge/internal/widgetauth"
)

type fakeWS struct {
	typ    string
	cors   []string
	access bool // result of UserCanAccessWorkspace
}

func (f fakeWS) WorkspaceWidget(_ context.Context, id string) (string, []string, string, string, error) {
	if id == "missing" {
		return "", nil, "", "", errors.New("not found")
	}
	return f.typ, f.cors, "#9964ff", "Support", nil
}

func (f fakeWS) UserCanAccessWorkspace(_ context.Context, _, _ string) (bool, error) {
	return f.access, nil
}

func widgetCfg() config.Config {
	return config.Config{
		Port: "8080", LogLevel: "error",
		WidgetTokenSecret: "test-secret", WidgetTokenTTLSeconds: 1800,
		JWTSecret: "jwt-test-secret",
	}
}

func adminToken(t *testing.T, role, sub string) string {
	t.Helper()
	tok, err := widgetauth.SignHS256("jwt-test-secret", map[string]any{
		"aud": "admin", "type": "access", "role": role, "sub": sub,
		"exp": time.Now().Add(time.Hour).Unix(),
	})
	if err != nil {
		t.Fatalf("mint admin token: %v", err)
	}
	return tok
}

func newSrv(t *testing.T, deps Deps) *http.Server {
	t.Helper()
	return New(widgetCfg(), slog.New(slog.NewTextHandler(io.Discard, nil)), deps)
}

func TestWidgetTokenIssuedForExternalAllowedOrigin(t *testing.T) {
	deps := mockDeps()
	deps.WSInfo = fakeWS{typ: "EXTERNAL", cors: []string{"https://acme.example"}}
	srv := newSrv(t, deps)

	req := httptest.NewRequest(http.MethodPost, "/api/v1/widget/token", strings.NewReader(`{"workspace_id":"`+widgetWS+`"}`))
	req.Header.Set("Origin", "https://acme.example")
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d (%s)", rec.Code, rec.Body.String())
	}
	if got := rec.Header().Get("Access-Control-Allow-Origin"); got != "https://acme.example" {
		t.Fatalf("expected echoed ACAO, got %q", got)
	}
	if !strings.Contains(rec.Body.String(), `"token"`) {
		t.Fatalf("expected a token in the body, got %s", rec.Body.String())
	}
}

func TestWidgetTokenRejectsInternalWorkspace(t *testing.T) {
	deps := mockDeps()
	deps.WSInfo = fakeWS{typ: "INTERNAL", cors: []string{"https://acme.example"}}
	srv := newSrv(t, deps)

	req := httptest.NewRequest(http.MethodPost, "/api/v1/widget/token", strings.NewReader(`{"workspace_id":"`+widgetWS+`"}`))
	req.Header.Set("Origin", "https://acme.example")
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusNotFound {
		t.Fatalf("expected 404 for INTERNAL workspace, got %d", rec.Code)
	}
}

func TestWidgetTokenRejectsDisallowedOrigin(t *testing.T) {
	deps := mockDeps()
	deps.WSInfo = fakeWS{typ: "EXTERNAL", cors: []string{"https://acme.example"}}
	srv := newSrv(t, deps)

	req := httptest.NewRequest(http.MethodPost, "/api/v1/widget/token", strings.NewReader(`{"workspace_id":"`+widgetWS+`"}`))
	req.Header.Set("Origin", "https://evil.example")
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusForbidden {
		t.Fatalf("expected 403 for disallowed origin, got %d", rec.Code)
	}
}

func TestExternalChatRequiresWidgetToken(t *testing.T) {
	deps := mockDeps()
	deps.WSInfo = fakeWS{typ: "EXTERNAL", cors: []string{"https://acme.example"}}
	srv := newSrv(t, deps)

	// Allowed origin but no widget token -> 401.
	req := httptest.NewRequest(http.MethodPost, "/api/v1/chat/stream",
		strings.NewReader(`{"workspace_id":"wsX","message":"hi"}`))
	req.Header.Set("Origin", "https://acme.example")
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401 without widget token, got %d", rec.Code)
	}
}

func TestExternalChatAcceptsValidWidgetToken(t *testing.T) {
	deps := mockDeps()
	deps.WSInfo = fakeWS{typ: "EXTERNAL", cors: []string{"https://acme.example"}}
	srv := newSrv(t, deps)

	tok, _ := widgetauth.Mint("test-secret", "wsX", 30*time.Minute, time.Now())
	req := httptest.NewRequest(http.MethodPost, "/api/v1/chat/stream",
		strings.NewReader(`{"workspace_id":"wsX","message":"hi"}`))
	req.Header.Set("Origin", "https://acme.example")
	req.Header.Set("Authorization", "Bearer "+tok)
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200 with valid widget token, got %d (%s)", rec.Code, rec.Body.String())
	}
	if !strings.Contains(rec.Body.String(), "[DONE]") {
		t.Fatalf("expected an SSE stream, got %s", rec.Body.String())
	}
}

func TestExternalChatRejectsTokenForOtherWorkspace(t *testing.T) {
	deps := mockDeps()
	deps.WSInfo = fakeWS{typ: "EXTERNAL", cors: []string{"https://acme.example"}}
	srv := newSrv(t, deps)

	// Token bound to a different workspace must not unlock wsX.
	tok, _ := widgetauth.Mint("test-secret", "other-ws", 30*time.Minute, time.Now())
	req := httptest.NewRequest(http.MethodPost, "/api/v1/chat/stream",
		strings.NewReader(`{"workspace_id":"wsX","message":"hi"}`))
	req.Header.Set("Origin", "https://acme.example")
	req.Header.Set("Authorization", "Bearer "+tok)
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401 for cross-workspace token, got %d", rec.Code)
	}
}

func TestInternalChatRequiresAdminToken(t *testing.T) {
	deps := mockDeps()
	deps.WSInfo = fakeWS{typ: "INTERNAL", access: true}
	srv := newSrv(t, deps)

	req := httptest.NewRequest(http.MethodPost, "/api/v1/chat/stream",
		strings.NewReader(`{"workspace_id":"wsX","message":"hi"}`))
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401 without an admin token, got %d", rec.Code)
	}
}

// The SUPER_ADMIN role claim alone grants nothing: the store decides access
// (org-scoped SUPER_ADMIN bypass, platform admins cross-org). A SUPER_ADMIN of
// another org must not reach a workspace the store denies — e.g. a public
// widget workspace whose id is printed in every embed snippet.
func TestInternalChatSuperAdminClaimDoesNotBypassStore(t *testing.T) {
	deps := mockDeps()
	deps.WSInfo = fakeWS{typ: "INTERNAL", access: false} // store: other org
	srv := newSrv(t, deps)

	req := httptest.NewRequest(http.MethodPost, "/api/v1/chat/stream",
		strings.NewReader(`{"workspace_id":"wsX","message":"hi"}`))
	req.Header.Set("Authorization", "Bearer "+adminToken(t, "SUPER_ADMIN", "su"))
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusNotFound {
		t.Fatalf("expected 404 for a cross-org super admin, got %d (%s)", rec.Code, rec.Body.String())
	}
}

func TestInternalChatSuperAdminAllowedWhenStoreAllows(t *testing.T) {
	deps := mockDeps()
	deps.WSInfo = fakeWS{typ: "INTERNAL", access: true} // store: same org
	srv := newSrv(t, deps)

	req := httptest.NewRequest(http.MethodPost, "/api/v1/chat/stream",
		strings.NewReader(`{"workspace_id":"wsX","message":"hi"}`))
	req.Header.Set("Authorization", "Bearer "+adminToken(t, "SUPER_ADMIN", "su"))
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200 for an in-org super admin, got %d (%s)", rec.Code, rec.Body.String())
	}
}

func TestInternalChatMemberAllowed(t *testing.T) {
	deps := mockDeps()
	deps.WSInfo = fakeWS{typ: "INTERNAL", access: true}
	srv := newSrv(t, deps)

	req := httptest.NewRequest(http.MethodPost, "/api/v1/chat/stream",
		strings.NewReader(`{"workspace_id":"wsX","message":"hi"}`))
	req.Header.Set("Authorization", "Bearer "+adminToken(t, "STAFF", "u1"))
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200 for a workspace member, got %d (%s)", rec.Code, rec.Body.String())
	}
}

func TestInternalChatNonMemberNotFound(t *testing.T) {
	deps := mockDeps()
	deps.WSInfo = fakeWS{typ: "INTERNAL", access: false}
	srv := newSrv(t, deps)

	req := httptest.NewRequest(http.MethodPost, "/api/v1/chat/stream",
		strings.NewReader(`{"workspace_id":"wsX","message":"hi"}`))
	req.Header.Set("Authorization", "Bearer "+adminToken(t, "STAFF", "u2"))
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusNotFound {
		t.Fatalf("expected 404 for a non-member, got %d", rec.Code)
	}
}

func newSrvWithCfg(t *testing.T, cfg config.Config, deps Deps) *http.Server {
	t.Helper()
	return New(cfg, slog.New(slog.NewTextHandler(io.Discard, nil)), deps)
}
