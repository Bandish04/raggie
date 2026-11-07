// SPDX-License-Identifier: Apache-2.0

package vectorstore

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"
	"time"

	"github.com/alicangunduz/raggie/services/edge/internal/ports"
)

func TestQdrantReady(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/readyz" {
			t.Fatalf("path = %q, want /readyz", r.URL.Path)
		}
		w.WriteHeader(http.StatusOK)
	}))
	defer srv.Close()

	if err := NewQdrantStore(srv.URL).Ready(context.Background()); err != nil {
		t.Fatal(err)
	}
}

func TestQdrantSearchDecodesResponseBeforeDraining(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/collections/raggie_chunks_d2/points/query" {
			t.Fatalf("path = %q", r.URL.Path)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"result":{"points":[{"id":"p1","score":0.9,"payload":{"document_id":"d1","filename":"policy.md","chunk_index":3,"chunk_kind":"outline","section_path":"# Policy","text":"policy text"}}]}}`)
	}))
	defer srv.Close()

	hits, err := NewQdrantStore(srv.URL).Search(
		context.Background(),
		[]string{"workspace-1"},
		ports.QueryVectors{Dense: []float32{0.25, 0.5}},
		4,
	)
	if err != nil {
		t.Fatal(err)
	}
	if len(hits) != 1 || hits[0].DocumentID != "d1" ||
		hits[0].Filename != "policy.md" || hits[0].ChunkIndex != 3 ||
		hits[0].ChunkKind != "outline" || hits[0].Section != "# Policy" ||
		hits[0].Text != "policy text" {
		t.Fatalf("hits = %#v", hits)
	}
}

// Live test against Qdrant; skipped unless QDRANT_TEST_URL is set.
func TestQdrantSearchIsWorkspaceIsolated(t *testing.T) {
	base := os.Getenv("QDRANT_TEST_URL")
	if base == "" {
		t.Skip("QDRANT_TEST_URL not set")
	}
	coll := CollectionName(4)
	httpc := &http.Client{Timeout: 10 * time.Second}

	do := func(method, path string, body any) int {
		var r io.Reader
		if body != nil {
			b, _ := json.Marshal(body)
			r = bytes.NewReader(b)
		}
		req, err := http.NewRequest(method, base+path, r) // #nosec G704 -- test helper for the local test Qdrant
		if err != nil {
			t.Fatal(err)
		}
		if body != nil {
			req.Header.Set("Content-Type", "application/json")
		}
		resp, err := httpc.Do(req) // #nosec G704 -- test helper for the local test Qdrant
		if err != nil {
			t.Fatal(err)
		}
		_ = resp.Body.Close()
		return resp.StatusCode
	}

	do(http.MethodDelete, "/collections/"+coll, nil)
	// Named "dense" vector + named "bm25" sparse vector (the hybrid schema).
	do(http.MethodPut, "/collections/"+coll, map[string]any{
		"vectors":        map[string]any{"dense": map[string]any{"size": 4, "distance": "Cosine"}},
		"sparse_vectors": map[string]any{"bm25": map[string]any{"modifier": "idf"}},
	})
	do(http.MethodPut, "/collections/"+coll+"/points?wait=true", map[string]any{
		"points": []any{
			map[string]any{"id": 1, "vector": map[string]any{"dense": []float32{1, 0, 0, 0}}, "payload": map[string]any{
				"workspace_id": "ws-A", "document_id": "d1", "filename": "a.txt", "text": "alpha",
			}},
			map[string]any{"id": 2, "vector": map[string]any{"dense": []float32{0, 1, 0, 0}}, "payload": map[string]any{
				"workspace_id": "ws-B", "document_id": "d2", "filename": "b.txt", "text": "beta",
			}},
		},
	})

	// Dense-only path (empty sparse) against the named-vector collection.
	store := NewQdrantStore(base)
	hits, err := store.Search(context.Background(), []string{"ws-A"}, ports.QueryVectors{Dense: []float32{1, 0, 0, 0}}, 4)
	if err != nil {
		t.Fatal(err)
	}
	if len(hits) != 1 || hits[0].Text != "alpha" || hits[0].DocumentID != "d1" {
		t.Fatalf("expected only ws-A's alpha chunk, got %+v", hits)
	}

	other, err := store.Search(context.Background(), []string{"ws-B"}, ports.QueryVectors{Dense: []float32{1, 0, 0, 0}}, 4)
	if err != nil {
		t.Fatal(err)
	}
	if len(other) != 1 || other[0].Text != "beta" {
		t.Fatalf("expected only ws-B's beta chunk, got %+v", other)
	}
}

func TestQdrantSendsAPIKeyWhenConfigured(t *testing.T) {
	var seen []string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		seen = append(seen, r.URL.Path+"="+r.Header.Get("api-key"))
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"result":{"points":[]}}`)
	}))
	defer srv.Close()

	store := NewQdrantStore(srv.URL).WithAPIKey("qdrant-key")
	if err := store.Ready(context.Background()); err != nil {
		t.Fatal(err)
	}
	if _, err := store.Search(context.Background(), []string{"ws"}, ports.QueryVectors{Dense: []float32{0.1, 0.2}}, 2); err != nil {
		t.Fatal(err)
	}
	if len(seen) != 2 || seen[0] != "/readyz=qdrant-key" || seen[1] != "/collections/raggie_chunks_d2/points/query=qdrant-key" {
		t.Fatalf("api-key header not sent on every request: %v", seen)
	}
}

func TestQdrantOmitsAPIKeyWhenUnset(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if _, ok := r.Header["Api-Key"]; ok {
			t.Errorf("unexpected api-key header")
		}
		w.WriteHeader(http.StatusOK)
	}))
	defer srv.Close()
	if err := NewQdrantStore(srv.URL).WithAPIKey("").Ready(context.Background()); err != nil {
		t.Fatal(err)
	}
}
