// SPDX-License-Identifier: Apache-2.0

package llm

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/alicangunduz/raggie/services/edge/internal/config"
	"github.com/alicangunduz/raggie/services/edge/internal/ports"
)

type observedChatRequest struct {
	Authorization string
	Model         string
	MaxTokens     int
	Reasoning     string
	HasTools      bool
}

func modelProviderServer(t *testing.T, model string, observed chan<- observedChatRequest) *httptest.Server {
	t.Helper()
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/models":
			w.Header().Set("Content-Type", "application/json")
			_, _ = io.WriteString(w, `{"data":[{"id":"`+model+`"}]}`)
		case "/chat/completions":
			var body map[string]any
			if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
				t.Errorf("decode request: %v", err)
			}
			_, hasTools := body["tools"]
			observed <- observedChatRequest{
				Authorization: r.Header.Get("Authorization"),
				Model:         body["model"].(string),
				MaxTokens:     int(body["max_tokens"].(float64)),
				Reasoning:     valueString(body["reasoning_effort"]),
				HasTools:      hasTools,
			}
			w.Header().Set("Content-Type", "text/event-stream")
			_, _ = io.WriteString(w, "data: [DONE]\n\n")
		default:
			http.NotFound(w, r)
		}
	}))
}

func valueString(value any) string {
	text, _ := value.(string)
	return text
}

func TestChatRouterUsesCanonicalRouteAndProviderCredentials(t *testing.T) {
	observed := make(chan observedChatRequest, 1)
	server := modelProviderServer(t, "qwen3:14b", observed)
	defer server.Close()

	router, err := NewChatRouter([]config.ModelProfile{{
		ID:             "local-general",
		Provider:       "ollama",
		BaseURL:        server.URL,
		APIKey:         "local-secret",
		UpstreamModel:  "qwen3:14b",
		MaxConcurrency: 2,
		MaxTokens:      4096,
		Capabilities:   []string{config.CapabilityReasoning},
	}}, "local-general")
	if err != nil {
		t.Fatal(err)
	}

	stream, err := router.Stream(context.Background(), ports.ChatRequest{
		Model:           "local-general",
		Messages:        []ports.Message{{Role: ports.RoleUser, Content: "hello"}},
		ReasoningEffort: "high",
	})
	if err != nil {
		t.Fatal(err)
	}
	for range stream {
	}
	request := <-observed
	if request.Model != "qwen3:14b" || request.Authorization != "Bearer local-secret" {
		t.Fatalf("unexpected upstream route: %+v", request)
	}
	if request.MaxTokens != 4096 || request.Reasoning != "high" {
		t.Fatalf("profile defaults/capabilities not applied: %+v", request)
	}
}

func TestChatRouterEnforcesCapabilitiesAndUnknownModels(t *testing.T) {
	observed := make(chan observedChatRequest, 1)
	server := modelProviderServer(t, "text-only", observed)
	defer server.Close()
	router, err := NewChatRouter([]config.ModelProfile{{
		ID:             "text",
		Provider:       "local",
		BaseURL:        server.URL,
		UpstreamModel:  "text-only",
		MaxConcurrency: 1,
		MaxTokens:      512,
	}}, "text")
	if err != nil {
		t.Fatal(err)
	}

	_, err = router.Stream(context.Background(), ports.ChatRequest{
		Model: "missing", Messages: []ports.Message{{Role: ports.RoleUser, Content: "x"}},
	})
	if !errors.Is(err, ErrUnknownModel) {
		t.Fatalf("unknown canonical model should fail closed: %v", err)
	}
	_, err = router.Stream(context.Background(), ports.ChatRequest{
		Model: "text",
		Messages: []ports.Message{{
			Role: ports.RoleUser,
			Parts: []ports.ContentPart{{
				Type: "image_url",
				ImageURL: &ports.ImageURLPart{
					URL: "data:image/png;base64,AA==",
				},
			}},
		}},
	})
	if !errors.Is(err, ErrUnsupportedModelCapability) {
		t.Fatalf("vision should be rejected before provider call: %v", err)
	}
	_, err = router.Stream(context.Background(), ports.ChatRequest{
		Model:    "text",
		Messages: []ports.Message{{Role: ports.RoleUser, Content: "x"}},
		Tools:    []ports.ToolSpec{{Name: "search"}},
	})
	if !errors.Is(err, ErrUnsupportedModelCapability) {
		t.Fatalf("tools should be rejected before provider call: %v", err)
	}

	stream, err := router.Stream(context.Background(), ports.ChatRequest{
		Model:           "text",
		Messages:        []ports.Message{{Role: ports.RoleUser, Content: "x"}},
		ReasoningEffort: "high",
	})
	if err != nil {
		t.Fatal(err)
	}
	for range stream {
	}
	if request := <-observed; request.Reasoning != "" {
		t.Fatalf("reasoning_effort leaked to a non-reasoning model: %+v", request)
	}
}

func TestChatRouterProviderPoolsAreIndependent(t *testing.T) {
	localObserved := make(chan observedChatRequest, 1)
	managedObserved := make(chan observedChatRequest, 1)
	local := modelProviderServer(t, "local-upstream", localObserved)
	defer local.Close()
	managed := modelProviderServer(t, "managed-upstream", managedObserved)
	defer managed.Close()

	router, err := NewChatRouter([]config.ModelProfile{
		{
			ID: "local", Provider: "local", BaseURL: local.URL,
			UpstreamModel: "local-upstream", MaxConcurrency: 1, MaxTokens: 256,
		},
		{
			ID: "managed", Provider: "managed", BaseURL: managed.URL,
			UpstreamModel: "managed-upstream", MaxConcurrency: 1, MaxTokens: 256,
		},
	}, "local")
	if err != nil {
		t.Fatal(err)
	}
	if !router.providers["local"].pool.tryAcquire() {
		t.Fatal("failed to occupy local provider pool")
	}
	defer router.providers["local"].pool.release()

	_, err = router.Stream(context.Background(), ports.ChatRequest{
		Model: "local", Messages: []ports.Message{{Role: ports.RoleUser, Content: "x"}},
	})
	if !errors.Is(err, ErrUpstreamBusy) {
		t.Fatalf("occupied local pool should shed locally: %v", err)
	}
	stream, err := router.Stream(context.Background(), ports.ChatRequest{
		Model: "managed", Messages: []ports.Message{{Role: ports.RoleUser, Content: "x"}},
	})
	if err != nil {
		t.Fatalf("managed provider must remain available: %v", err)
	}
	for range stream {
	}
	request := <-managedObserved
	if request.Model != "managed-upstream" {
		t.Fatalf("unexpected managed route: %+v", request)
	}
}

func TestChatRouterListsCanonicalProfileAvailability(t *testing.T) {
	observed := make(chan observedChatRequest, 1)
	server := modelProviderServer(t, "available-upstream", observed)
	defer server.Close()
	router, err := NewChatRouter([]config.ModelProfile{
		{
			ID: "available", Provider: "p", BaseURL: server.URL,
			UpstreamModel: "available-upstream", MaxConcurrency: 1, MaxTokens: 256,
			Capabilities: []string{config.CapabilityTools},
		},
		{
			ID: "offline", Provider: "p", BaseURL: server.URL,
			UpstreamModel: "missing-upstream", MaxConcurrency: 1, MaxTokens: 256,
		},
	}, "available")
	if err != nil {
		t.Fatal(err)
	}
	profiles, err := router.ListModelProfiles(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if len(profiles) != 2 || profiles[0].ID != "available" || !profiles[0].Available ||
		profiles[1].ID != "offline" || profiles[1].Available {
		t.Fatalf("unexpected profiles: %+v", profiles)
	}
	models, err := router.ListModels(context.Background())
	if err != nil || len(models) != 1 || models[0] != "available" {
		t.Fatalf("unexpected available models: %v, %v", models, err)
	}
	if err := router.Ready(context.Background()); err != nil {
		t.Fatalf("available default model should be ready: %v", err)
	}
}

func TestChatRouterRejectsConflictingProviderRoutes(t *testing.T) {
	_, err := NewChatRouter([]config.ModelProfile{
		{
			ID: "one", Provider: "shared", BaseURL: "http://one.invalid/v1",
			UpstreamModel: "one", MaxConcurrency: 1, MaxTokens: 256,
		},
		{
			ID: "two", Provider: "shared", BaseURL: "http://two.invalid/v1",
			UpstreamModel: "two", MaxConcurrency: 1, MaxTokens: 256,
		},
	}, "one")
	if err == nil {
		t.Fatal("conflicting routes under one provider must fail")
	}
}

func TestChatRouterListsConfiguredModelsWhenProviderIsDown(t *testing.T) {
	router, err := NewChatRouter([]config.ModelProfile{{
		ID: "offline", Provider: "local", BaseURL: "http://127.0.0.1:1/v1",
		UpstreamModel: "offline-upstream", MaxConcurrency: 1, MaxTokens: 256,
	}}, "offline")
	if err != nil {
		t.Fatal(err)
	}
	profiles, err := router.ListModelProfiles(context.Background())
	if err != nil {
		t.Fatalf("configured metadata should survive discovery outage: %v", err)
	}
	if len(profiles) != 1 || profiles[0].ID != "offline" || profiles[0].Available {
		t.Fatalf("unexpected offline metadata: %+v", profiles)
	}
}

// A profile's response_header_timeout_seconds reaches its provider's transport;
// two routes of one provider may not disagree on it.
func TestChatRouterAppliesPerProviderHeaderTimeout(t *testing.T) {
	router, err := NewChatRouter([]config.ModelProfile{
		{ID: "slow", Provider: "ollama", BaseURL: "http://ollama.invalid/v1", UpstreamModel: "qwen3:4b",
			MaxConcurrency: 1, MaxTokens: 256, ResponseHeaderTimeoutSeconds: 300},
		{ID: "fast", Provider: "managed", BaseURL: "http://managed.invalid/v1", UpstreamModel: "m",
			MaxConcurrency: 1, MaxTokens: 256, ResponseHeaderTimeoutSeconds: 60},
	}, "slow")
	if err != nil {
		t.Fatal(err)
	}
	for name, want := range map[string]time.Duration{"ollama": 300 * time.Second, "managed": 60 * time.Second} {
		got := router.providers[name].http.Transport.(*http.Transport).ResponseHeaderTimeout
		if got != want {
			t.Fatalf("%s header timeout = %s, want %s", name, got, want)
		}
	}
	_, err = NewChatRouter([]config.ModelProfile{
		{ID: "a", Provider: "shared", BaseURL: "http://s.invalid/v1", UpstreamModel: "a", MaxConcurrency: 1, MaxTokens: 256, ResponseHeaderTimeoutSeconds: 60},
		{ID: "b", Provider: "shared", BaseURL: "http://s.invalid/v1", UpstreamModel: "b", MaxConcurrency: 1, MaxTokens: 256, ResponseHeaderTimeoutSeconds: 300},
	}, "a")
	if err == nil {
		t.Fatal("routes of one provider with different header timeouts must conflict")
	}
}
