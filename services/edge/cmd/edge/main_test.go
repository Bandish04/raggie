// SPDX-License-Identifier: Apache-2.0

package main

import (
	"context"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"

	"github.com/alicangunduz/raggie/services/edge/internal/config"
)

// The embeddings gateway authenticates callers with INTERNAL_API_SECRET; the LLM
// provider key must never be sent to it (it would leak to a cloud upstream's
// logs if the gateway were misconfigured, and it is not the gateway's secret).
func TestEmbeddingsClientsSendInternalSecretNeverLLMKey(t *testing.T) {
	const llmKey = "llm-provider-key-must-not-leak"
	for _, tc := range []struct {
		name, secret, want string
	}{
		{"secret set", "internal-secret-0123456789abcdef", "Bearer internal-secret-0123456789abcdef"},
		{"secret unset (local gateway)", "", ""},
	} {
		t.Run(tc.name, func(t *testing.T) {
			var (
				mu   sync.Mutex
				seen = map[string]string{}
			)
			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				mu.Lock()
				seen[r.URL.Path] = r.Header.Get("Authorization")
				mu.Unlock()
				w.Header().Set("Content-Type", "application/json")
				switch r.URL.Path {
				case "/v1/query":
					_, _ = io.WriteString(w, `{"dense":[1],"sparse":{"indices":[],"values":[]},`+
						`"collection":"raggie_chunks_d1","fingerprint":"0a1b2c3d"}`)
				case "/v1/rerank":
					_, _ = io.WriteString(w, `{"results":[{"index":0,"score":1}]}`)
				default:
					w.WriteHeader(http.StatusNotFound)
				}
			}))
			defer srv.Close()

			cfg := config.Config{
				EmbeddingsBaseURL:   srv.URL + "/v1",
				LLMaaSAPIKey:        llmKey,
				InternalAPISecret:   tc.secret,
				EmbedMaxConcurrency: 4,
				RerankEnabled:       true,
			}
			queryEmbedder, reranker := newEmbeddingsClients(cfg, slog.New(slog.NewTextHandler(io.Discard, nil)))
			if reranker == nil {
				t.Fatal("RERANK_ENABLED=true must wire the reranker")
			}
			if _, err := queryEmbedder.EmbedQuery(context.Background(), "q"); err != nil {
				t.Fatal(err)
			}
			if _, err := reranker.Rerank(context.Background(), "q", []string{"a"}, 1); err != nil {
				t.Fatal(err)
			}

			mu.Lock()
			defer mu.Unlock()
			for _, path := range []string{"/v1/query", "/v1/rerank"} {
				got, ok := seen[path]
				if !ok {
					t.Fatalf("%s was never called", path)
				}
				if strings.Contains(got, llmKey) {
					t.Fatalf("%s received the LLM provider key", path)
				}
				if got != tc.want {
					t.Fatalf("%s Authorization = %q, want %q", path, got, tc.want)
				}
			}
		})
	}
}

func TestEmbeddingsClientsSkipRerankerWhenDisabled(t *testing.T) {
	_, reranker := newEmbeddingsClients(config.Config{EmbeddingsBaseURL: "http://unused/v1"}, slog.New(slog.NewTextHandler(io.Discard, nil)))
	if reranker != nil {
		t.Fatal("RERANK_ENABLED=false must leave the reranker unwired")
	}
}

// The edge refuses to start on a configuration Validate rejects (here:
// production without DATABASE_URL) or on a broken model registry; a
// development config starts.
func TestLoadConfigRefusesInvalidConfiguration(t *testing.T) {
	t.Setenv("RAGGIE_ENV", "production")
	t.Setenv("DATABASE_URL", "")
	if _, err := loadConfig(); err == nil || !strings.Contains(err.Error(), "DATABASE_URL") {
		t.Fatalf("expected the DATABASE_URL validation error, got %v", err)
	}

	t.Setenv("RAGGIE_ENV", "development")
	if _, err := loadConfig(); err != nil {
		t.Fatalf("development config must load: %v", err)
	}

	t.Setenv("LLM_MODEL_PROFILES_JSON", `[{"id":"default","provider":"p","base_url":"http://localhost:1/v1","capabilities":["magic"]}]`)
	if _, err := loadConfig(); err == nil || !strings.Contains(err.Error(), "model provider registry") {
		t.Fatalf("expected the model registry error, got %v", err)
	}
}

// Qdrant may require an API key: the store main builds sends QDRANT_API_KEY
// on its requests.
func TestVectorStoreSendsQdrantAPIKey(t *testing.T) {
	var got string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		got = r.Header.Get("api-key")
		w.WriteHeader(http.StatusOK)
	}))
	defer srv.Close()
	vs := newVectorStore(config.Config{QdrantURL: srv.URL, QdrantAPIKey: "qdrant-key-0123456789"})
	if err := vs.Ready(context.Background()); err != nil {
		t.Fatal(err)
	}
	if got != "qdrant-key-0123456789" {
		t.Fatalf("api-key header = %q, want the configured QDRANT_API_KEY", got)
	}
}
