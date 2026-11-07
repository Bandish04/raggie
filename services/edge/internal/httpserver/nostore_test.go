// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/alicangunduz/raggie/services/edge/internal/config"
	"github.com/alicangunduz/raggie/services/edge/internal/ports/mock"
	"github.com/alicangunduz/raggie/services/edge/internal/rag"
)

// Without a store (no DATABASE_URL — only possible in development) the edge
// cannot resolve the workspace type, verify membership or token revocation, so
// it must refuse to serve chat rather than serve it unauthenticated.
func TestChatWithoutStoreIsUnavailable(t *testing.T) {
	deps := Deps{
		RAG:  rag.New(mock.QueryEmbedder{Dim: 8}, mock.VectorStore{}),
		Chat: mock.ChatProvider{Response: "must not stream"},
	}
	srv := New(config.Config{Env: "development"}, discardLogger(), deps)
	for name, token := range map[string]string{"anonymous": "", "unverifiable token": "x.y.z"} {
		req := httptest.NewRequest(http.MethodPost, "/api/v1/chat/stream",
			strings.NewReader(`{"workspace_id":"w1","message":"merhaba"}`))
		if token != "" {
			req.Header.Set("Authorization", "Bearer "+token)
		}
		rec := httptest.NewRecorder()
		srv.Handler.ServeHTTP(rec, req)
		if rec.Code != http.StatusServiceUnavailable || strings.Contains(rec.Body.String(), "must not stream") {
			t.Fatalf("%s: got %d %s, want 503 unavailable", name, rec.Code, rec.Body.String())
		}
		if !strings.Contains(rec.Body.String(), errCodeUnavailable) {
			t.Fatalf("%s: body %s lacks %q", name, rec.Body.String(), errCodeUnavailable)
		}
	}
}

// run-task skips the owner access re-check without a store, so it is refused
// the same way even with the correct internal secret.
func TestRunTaskWithoutStoreIsUnavailable(t *testing.T) {
	srv := New(config.Config{InternalAPISecret: "s3cr3t"}, discardLogger(), Deps{
		RAG:  rag.New(mock.QueryEmbedder{Dim: 8}, mock.VectorStore{}),
		Chat: mock.ChatProvider{Response: "must not run"},
	})
	req := httptest.NewRequest(http.MethodPost, "/api/v1/internal/run-task",
		strings.NewReader(`{"workspace_id":"w1","user_id":"u1","prompt":"merhaba"}`))
	req.Header.Set("X-Internal-Secret", "s3cr3t")
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("got %d %s, want 503", rec.Code, rec.Body.String())
	}
}
