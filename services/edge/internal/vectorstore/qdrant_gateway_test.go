// SPDX-License-Identifier: Apache-2.0

package vectorstore

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"

	"github.com/alicangunduz/raggie/services/edge/internal/ports"
)

func TestQdrantSearchUsesGatewayCollection(t *testing.T) {
	var path string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		path = r.URL.Path
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"result":{"points":[]}}`)
	}))
	defer srv.Close()

	// The vector is 2-dim but the gateway names a fingerprinted collection: the
	// gateway's answer wins, the vector length is never consulted.
	_, err := NewQdrantStore(srv.URL).Search(context.Background(), []string{"ws"},
		ports.QueryVectors{Dense: []float32{0.1, 0.2}, Collection: "raggie_chunks_d1024_0a1b2c3d"}, 4)
	if err != nil {
		t.Fatal(err)
	}
	if path != "/collections/raggie_chunks_d1024_0a1b2c3d/points/query" {
		t.Fatalf("path = %q", path)
	}
}

func TestQdrantSearchFallsBackToDimensionForOlderGateway(t *testing.T) {
	var path string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		path = r.URL.Path
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"result":{"points":[]}}`)
	}))
	defer srv.Close()

	_, err := NewQdrantStore(srv.URL).Search(context.Background(), []string{"ws"},
		ports.QueryVectors{Dense: []float32{0.1, 0.2, 0.3}}, 4)
	if err != nil {
		t.Fatal(err)
	}
	if path != "/collections/raggie_chunks_d3/points/query" {
		t.Fatalf("path = %q, want the legacy dimension-derived collection", path)
	}
}

func TestQdrantSearchMissingCollectionIsTyped(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusNotFound)
		_, _ = io.WriteString(w, `{"status":{"error":"Not found: Collection `+"`raggie_chunks_d1024`"+` doesn't exist!"},"time":0}`)
	}))
	defer srv.Close()

	_, err := NewQdrantStore(srv.URL).Search(context.Background(), []string{"ws"},
		ports.QueryVectors{Dense: []float32{0.1}, Collection: "raggie_chunks_d1024"}, 4)
	if !errors.Is(err, ports.ErrCollectionMissing) {
		t.Fatalf("err = %v, want ports.ErrCollectionMissing", err)
	}
}

func TestQdrantSearchOtherErrorsAreNotCollectionMissing(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
	}))
	defer srv.Close()

	_, err := NewQdrantStore(srv.URL).Search(context.Background(), []string{"ws"},
		ports.QueryVectors{Dense: []float32{0.1}}, 4)
	if err == nil || errors.Is(err, ports.ErrCollectionMissing) {
		t.Fatalf("err = %v, want a plain upstream error", err)
	}
}

func TestQdrantSearchRejectsMalformedCollection(t *testing.T) {
	called := false
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		called = true
	}))
	defer srv.Close()

	for _, name := range []string{"../../collections", "raggie_chunks_d1024/points", "other", "raggie_chunks_d1024_XYZ"} {
		_, err := NewQdrantStore(srv.URL).Search(context.Background(), []string{"ws"},
			ports.QueryVectors{Dense: []float32{0.1}, Collection: name}, 4)
		if err == nil {
			t.Fatalf("collection %q must be rejected", name)
		}
	}
	if called {
		t.Fatal("a malformed collection name must never reach Qdrant")
	}
}

// The edge-side collection validator must accept exactly what the gateway
// contract allows (CI drift gate against contracts/embeddings_gateway.schema.json).
func TestCollectionPatternMatchesGatewayContract(t *testing.T) {
	path := filepath.Join("..", "..", "..", "..", "contracts", "embeddings_gateway.schema.json")
	data, err := os.ReadFile(path) // #nosec G304 -- fixed repo-relative contract path in a test
	if err != nil {
		t.Fatal(err)
	}
	var schema struct {
		Defs struct {
			Collection struct {
				Pattern string `json:"pattern"`
			} `json:"collection"`
		} `json:"$defs"`
	}
	if err := json.Unmarshal(data, &schema); err != nil {
		t.Fatal(err)
	}
	if got, want := collectionPattern.String(), schema.Defs.Collection.Pattern; got != want {
		t.Fatalf("collection pattern = %q, contract says %q", got, want)
	}
	for _, ok := range []string{"raggie_chunks_d1024", "raggie_chunks_d1536_0a1b2c3d", CollectionName(8)} {
		if !ValidCollectionName(ok) {
			t.Errorf("%q should be valid", ok)
		}
	}
}

// Live test against Qdrant; skipped unless QDRANT_TEST_URL is set. Verifies the
// real server answers a missing collection with 404 (→ ErrCollectionMissing).
func TestQdrantLiveMissingCollectionIsTyped(t *testing.T) {
	base := os.Getenv("QDRANT_TEST_URL")
	if base == "" {
		t.Skip("QDRANT_TEST_URL not set")
	}
	_, err := NewQdrantStore(base).Search(context.Background(), []string{"ws"},
		ports.QueryVectors{Dense: []float32{1, 0, 0, 0}, Collection: "raggie_chunks_d4_deadbeef"}, 4)
	if !errors.Is(err, ports.ErrCollectionMissing) {
		t.Fatalf("err = %v, want ports.ErrCollectionMissing", err)
	}
}
