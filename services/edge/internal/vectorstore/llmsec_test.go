// SPDX-License-Identifier: Apache-2.0

package vectorstore

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"reflect"
	"sync/atomic"
	"testing"

	"github.com/alicangunduz/raggie/services/edge/internal/ports"
)

// LLM/RAG security suite: tenant isolation lives in the Qdrant query itself.
// Every search must carry exactly the requested workspace set as a top-level
// filter (it propagates to both hybrid prefetches), whatever the query shape.
func TestLLMSecQdrantQueryAlwaysCarriesWorkspaceFilter(t *testing.T) {
	type sentQuery struct {
		Filter struct {
			Must []struct {
				Key   string `json:"key"`
				Match struct {
					Any []string `json:"any"`
				} `json:"match"`
			} `json:"must"`
		} `json:"filter"`
		Prefetch []map[string]any `json:"prefetch"`
	}
	var got sentQuery
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		got = sentQuery{}
		b, _ := io.ReadAll(r.Body)
		if err := json.Unmarshal(b, &got); err != nil {
			t.Errorf("bad query body: %v", err)
		}
		_, _ = io.WriteString(w, `{"result":{"points":[]}}`)
	}))
	defer srv.Close()
	store := NewQdrantStore(srv.URL)

	sparse := ports.SparseVector{Indices: []uint32{1}, Values: []float32{1}}
	for name, tc := range map[string]struct {
		ws     []string
		sparse ports.SparseVector
	}{
		"dense-only, one workspace":   {[]string{"ws-a"}, ports.SparseVector{}},
		"hybrid, one workspace":       {[]string{"ws-a"}, sparse},
		"hybrid, several workspaces":  {[]string{"ws-a", "ws-b"}, sparse},
		"dense-only, many workspaces": {[]string{"ws-a", "ws-b", "ws-c"}, ports.SparseVector{}},
	} {
		_, err := store.Search(context.Background(), tc.ws, ports.QueryVectors{Dense: []float32{0.1, 0.2}, Sparse: tc.sparse}, 5)
		if err != nil {
			t.Fatalf("%s: %v", name, err)
		}
		if len(got.Filter.Must) != 1 || got.Filter.Must[0].Key != "workspace_id" ||
			!reflect.DeepEqual(got.Filter.Must[0].Match.Any, tc.ws) {
			t.Fatalf("%s: filter = %+v, want workspace_id ∈ %v", name, got.Filter, tc.ws)
		}
		for _, p := range got.Prefetch {
			if _, ok := p["filter"]; ok {
				t.Fatalf("%s: a prefetch carries its own filter; isolation must come from the top-level one", name)
			}
		}
	}
}

// An empty workspace set must never become an unfiltered search: refuse it
// before any request leaves the edge.
func TestLLMSecQdrantRefusesEmptyWorkspaceSet(t *testing.T) {
	var calls atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		calls.Add(1)
		_, _ = io.WriteString(w, `{"result":{"points":[]}}`)
	}))
	defer srv.Close()
	store := NewQdrantStore(srv.URL)
	for name, ws := range map[string][]string{"nil": nil, "empty": {}, "blank id": {""}, "blank among ids": {"ws-a", " "}} {
		if _, err := store.Search(context.Background(), ws, ports.QueryVectors{Dense: []float32{0.1}}, 5); err == nil {
			t.Errorf("%s workspace set: search was not refused", name)
		}
	}
	if n := calls.Load(); n != 0 {
		t.Fatalf("%d queries reached Qdrant without a valid workspace filter", n)
	}
}
