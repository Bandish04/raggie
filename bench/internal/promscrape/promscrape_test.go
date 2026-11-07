// SPDX-License-Identifier: Apache-2.0

package promscrape

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
)

const body = `# HELP raggie_edge_up 1 if the edge process is up
# TYPE raggie_edge_up gauge
raggie_edge_up 1
raggie_edge_active_streams 42
raggie_edge_rerank_fail_open_total 3
go_goroutines{instance="x"} 1234
`

func TestValue(t *testing.T) {
	for name, want := range map[string]float64{
		"raggie_edge_active_streams": 42, "raggie_edge_up": 1, "go_goroutines": 1234,
	} {
		if got, ok := Value(body, name); !ok || got != want {
			t.Errorf("%s = %v, %v", name, got, ok)
		}
	}
	if _, ok := Value(body, "raggie_edge"); ok {
		t.Fatal("a prefix must not match")
	}
	if _, ok := Value(body, "missing"); ok {
		t.Fatal("missing metric")
	}
}

func TestScrapeSendsBearer(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer tok" {
			w.WriteHeader(http.StatusUnauthorized)
			return
		}
		_, _ = w.Write([]byte(body))
	}))
	defer srv.Close()
	got, err := Scrape(context.Background(), http.DefaultClient, srv.URL, "tok")
	if err != nil || got != body {
		t.Fatalf("scrape = %q, %v", got, err)
	}
	if _, err := Scrape(context.Background(), http.DefaultClient, srv.URL, ""); err == nil {
		t.Fatal("401 must be an error")
	}
}
