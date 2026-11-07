// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/alicangunduz/raggie/services/edge/internal/ports"
	"github.com/alicangunduz/raggie/services/edge/internal/widgetauth"
)

// stubModelLister is a local ports.ModelLister for tests (kept out of the shared
// mock package so its compile-time assertions stay minimal).
type stubModelLister struct {
	ids []string
	err error
}

func (s stubModelLister) ListModels(context.Context) ([]string, error) {
	return s.ids, s.err
}

type stubModelProfileLister struct {
	stubModelLister
	profiles []ports.ModelDescriptor
}

func (s stubModelProfileLister) ListModelProfiles(context.Context) ([]ports.ModelDescriptor, error) {
	return s.profiles, s.err
}

type stubTokenState struct {
	active bool
}

func (s stubTokenState) UserSessionActive(context.Context, string, string) (bool, error) {
	return s.active, nil
}

func adminSessionToken(t *testing.T) string {
	t.Helper()
	token, err := widgetauth.SignHS256("test-secret", map[string]any{
		"aud":  "admin",
		"type": "access",
		"sub":  "u1",
		"role": "WORKSPACE_ADMIN",
		"sid":  "session-1",
		"exp":  time.Now().Add(time.Hour).Unix(),
	})
	if err != nil {
		t.Fatal(err)
	}
	return token
}

func TestModelsEndpointReturnsIDs(t *testing.T) {
	// Reset the package cache so this test is order-independent.
	modelsCacheState = modelsCache{}
	srv := newSrv(t, Deps{Models: stubModelLister{ids: []string{"gpt-oss-120b", "qwen3-next-80b"}}})

	req := httptest.NewRequest(http.MethodGet, "/api/v1/models", nil)
	req.Header.Set("Authorization", "Bearer "+adminToken(t, "WORKSPACE_ADMIN", "u1"))
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rec.Code)
	}
	var body struct {
		Models []string `json:"models"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if len(body.Models) != 2 || body.Models[0] != "gpt-oss-120b" {
		t.Fatalf("unexpected models: %v", body.Models)
	}
}

func TestModelsEndpointReturnsCanonicalProviderProfiles(t *testing.T) {
	modelsCacheState = modelsCache{}
	srv := newSrv(t, Deps{Models: stubModelProfileLister{
		profiles: []ports.ModelDescriptor{
			{
				ID: "local", Provider: "ollama", UpstreamModel: "qwen3:14b",
				Capabilities: []string{"reasoning"}, Available: true,
			},
			{
				ID: "managed", Provider: "managed", UpstreamModel: "gpt-x",
				Capabilities: []string{"tools"}, Available: false,
			},
		},
	}})

	req := httptest.NewRequest(http.MethodGet, "/api/v1/models", nil)
	req.Header.Set("Authorization", "Bearer "+adminToken(t, "WORKSPACE_ADMIN", "u1"))
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rec.Code)
	}
	var body modelsResponse
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if len(body.Models) != 1 || body.Models[0] != "local" || len(body.Profiles) != 2 {
		t.Fatalf("unexpected provider profile response: %+v", body)
	}
}

func TestModelsEndpointDegradesOnProviderError(t *testing.T) {
	modelsCacheState = modelsCache{}
	srv := newSrv(t, Deps{Models: stubModelLister{err: errors.New("provider down")}})

	req := httptest.NewRequest(http.MethodGet, "/api/v1/models", nil)
	req.Header.Set("Authorization", "Bearer "+adminToken(t, "WORKSPACE_ADMIN", "u1"))
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected graceful 200 on provider error, got %d", rec.Code)
	}
	var body struct {
		Models []string `json:"models"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if len(body.Models) != 0 {
		t.Fatalf("expected empty list on provider error, got %v", body.Models)
	}
}

func TestModelsEndpointRequiresAuth(t *testing.T) {
	modelsCacheState = modelsCache{}
	srv := newSrv(t, Deps{Models: stubModelLister{ids: []string{"x"}}})

	req := httptest.NewRequest(http.MethodGet, "/api/v1/models", nil) // no token
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401 without a token, got %d", rec.Code)
	}
}

func TestModelsEndpointRejectsRevokedSession(t *testing.T) {
	modelsCacheState = modelsCache{}
	srv := newSrv(t, Deps{
		Models:     stubModelLister{ids: []string{"x"}},
		TokenState: stubTokenState{active: false},
	})

	req := httptest.NewRequest(http.MethodGet, "/api/v1/models", nil)
	req.Header.Set("Authorization", "Bearer "+adminSessionToken(t))
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401 for revoked session, got %d", rec.Code)
	}
}

// The pre-stream error contract: a malformed request returns the JSON shape
// {"error":<code>,"message":<friendly>} rather than a plain-text body.
func TestChatBadRequestReturnsJSONErrorContract(t *testing.T) {
	srv := New(testCfg(), slog.New(slog.NewTextHandler(io.Discard, nil)), mockDeps())

	req := httptest.NewRequest(http.MethodPost, "/api/v1/chat/stream", nil) // nil body -> decode error
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d", rec.Code)
	}
	if ct := rec.Header().Get("Content-Type"); ct != "application/json" {
		t.Fatalf("expected application/json error body, got %q", ct)
	}
	var body struct {
		Error   string `json:"error"`
		Message string `json:"message"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if body.Error != errCodeBadRequest || body.Message == "" {
		t.Fatalf("unexpected error body: %+v", body)
	}
}
