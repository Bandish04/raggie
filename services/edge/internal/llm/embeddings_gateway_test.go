// SPDX-License-Identifier: Apache-2.0

package llm

import (
	"bytes"
	"context"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

// Wire fixtures shaped exactly like contracts/embeddings_gateway.schema.json.
const (
	gatewayQueryBody = `{"dense":[0.25,0.5],"sparse":{"indices":[7],"values":[1]},` +
		`"collection":"raggie_chunks_d1024_0a1b2c3d","fingerprint":"0a1b2c3d"}`
	gatewayInfoBody = `{"provider":"openai_compatible","model":"text-embedding-3-large","dim":1024,` +
		`"fingerprint":"0a1b2c3d","collection":"raggie_chunks_d1024_0a1b2c3d","sparse_model":"Qdrant/bm25",` +
		`"reranker":{"provider":"cohere","model":"rerank-v3.5"},` +
		`"egress":{"dense_host":"api.openai.com","rerank_host":null},"future_field":true}`
)

func TestQueryEmbedderReturnsGatewayCollectionAndFingerprint(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, gatewayQueryBody)
	}))
	defer srv.Close()

	qv, err := NewQueryEmbedder(srv.URL+"/v1", "", 0, 4).EmbedQuery(context.Background(), "q")
	if err != nil {
		t.Fatal(err)
	}
	if qv.Collection != "raggie_chunks_d1024_0a1b2c3d" || qv.Fingerprint != "0a1b2c3d" {
		t.Fatalf("collection/fingerprint = %q/%q", qv.Collection, qv.Fingerprint)
	}
	if len(qv.Dense) != 2 || len(qv.Sparse.Indices) != 1 {
		t.Fatalf("vectors = %+v", qv)
	}
}

func TestQueryEmbedderSendsInternalBearerOnlyWhenSet(t *testing.T) {
	var got []string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		got = append(got, r.Header.Get("Authorization"))
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, gatewayQueryBody)
	}))
	defer srv.Close()

	if _, err := NewQueryEmbedder(srv.URL+"/v1", "internal-secret", 0, 4).EmbedQuery(context.Background(), "q"); err != nil {
		t.Fatal(err)
	}
	if _, err := NewQueryEmbedder(srv.URL+"/v1", "", 0, 4).EmbedQuery(context.Background(), "q"); err != nil {
		t.Fatal(err)
	}
	if len(got) != 2 || got[0] != "Bearer internal-secret" || got[1] != "" {
		t.Fatalf("Authorization headers = %q, want [Bearer internal-secret, <none>]", got)
	}
}

func TestQueryEmbedderTimeoutKnob(t *testing.T) {
	if got := NewQueryEmbedder("http://unused", "", 0, 1).http.Timeout; got != DefaultEmbedQueryTimeout {
		t.Fatalf("default query timeout = %s, want %s", got, DefaultEmbedQueryTimeout)
	}
	if DefaultEmbedQueryTimeout != 8*time.Second {
		t.Fatalf("DefaultEmbedQueryTimeout = %s, want 8s", DefaultEmbedQueryTimeout)
	}
	release := make(chan struct{})
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		<-release
	}))
	defer srv.Close()
	defer close(release)

	e := NewQueryEmbedder(srv.URL+"/v1", "", 50*time.Millisecond, 1)
	if e.http.Timeout != 50*time.Millisecond {
		t.Fatalf("configured query timeout = %s", e.http.Timeout)
	}
	start := time.Now()
	if _, err := e.EmbedQuery(context.Background(), "q"); err == nil {
		t.Fatal("a stalled gateway must time out")
	}
	if elapsed := time.Since(start); elapsed > 2*time.Second {
		t.Fatalf("timeout not honored: took %s", elapsed)
	}
}

func TestQueryEmbedderInfoParsesContractAndSendsBearer(t *testing.T) {
	var auth string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/info" || r.Method != http.MethodGet {
			t.Errorf("unexpected %s %s", r.Method, r.URL.Path)
		}
		auth = r.Header.Get("Authorization")
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, gatewayInfoBody)
	}))
	defer srv.Close()

	var logs bytes.Buffer
	e := NewQueryEmbedder(srv.URL+"/v1", "internal-secret", 0, 4).
		WithLogger(slog.New(slog.NewTextHandler(&logs, nil)))
	info, err := e.RefreshInfo(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if auth != "Bearer internal-secret" {
		t.Fatalf("Authorization = %q", auth)
	}
	if info.Provider != "openai_compatible" || info.Model != "text-embedding-3-large" || info.Dim != 1024 ||
		info.Fingerprint != "0a1b2c3d" || info.Collection != "raggie_chunks_d1024_0a1b2c3d" ||
		info.SparseModel != "Qdrant/bm25" || info.Reranker.Provider != "cohere" ||
		info.Reranker.Model != "rerank-v3.5" || info.Egress.DenseHost != "api.openai.com" ||
		info.Egress.RerankHost != "" {
		t.Fatalf("info = %+v", info)
	}
	if cached, ok := e.Info(); !ok || cached != info {
		t.Fatalf("cached info = %+v, %v", cached, ok)
	}
	for _, want := range []string{"provider=openai_compatible", "dim=1024", "collection=raggie_chunks_d1024_0a1b2c3d", "egress_dense_host=api.openai.com"} {
		if !strings.Contains(logs.String(), want) {
			t.Fatalf("profile log missing %q: %s", want, logs.String())
		}
	}
}

func TestQueryEmbedderInfoRejectsContractViolation(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"provider":"local","model":"m","dim":0,"fingerprint":"x","collection":""}`)
	}))
	defer srv.Close()

	e := NewQueryEmbedder(srv.URL+"/v1", "", 0, 4)
	if _, err := e.RefreshInfo(context.Background()); err == nil {
		t.Fatal("an info body without dim/collection must be rejected")
	}
	if _, ok := e.Info(); ok {
		t.Fatal("a rejected info body must not be cached")
	}
}

func TestQueryEmbedderReadyFetchesInfoLazily(t *testing.T) {
	var infoCalls atomic.Int32
	infoStatus := http.StatusOK
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/readyz":
			w.WriteHeader(http.StatusOK)
		case "/v1/info":
			infoCalls.Add(1)
			if infoStatus != http.StatusOK {
				w.WriteHeader(infoStatus)
				return
			}
			_, _ = io.WriteString(w, gatewayInfoBody)
		default:
			t.Errorf("unexpected path %s", r.URL.Path)
		}
	}))
	defer srv.Close()

	e := NewQueryEmbedder(srv.URL+"/v1", "s", 0, 4)
	if err := e.Ready(context.Background()); err != nil {
		t.Fatal(err)
	}
	if err := e.Ready(context.Background()); err != nil {
		t.Fatal(err)
	}
	if n := infoCalls.Load(); n != 1 {
		t.Fatalf("info fetched %d times; a cached profile must not be refetched", n)
	}
	if _, ok := e.Info(); !ok {
		t.Fatal("readiness should have cached the profile")
	}
}

func TestQueryEmbedderReadyToleratesOldGatewayButNotBadBearer(t *testing.T) {
	for _, tc := range []struct {
		name      string
		status    int
		wantReady bool
	}{
		{"older gateway without /v1/info", http.StatusNotFound, true},
		{"gateway error", http.StatusInternalServerError, true},
		{"wrong internal bearer", http.StatusUnauthorized, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if r.URL.Path == "/readyz" {
					w.WriteHeader(http.StatusOK)
					return
				}
				w.WriteHeader(tc.status)
			}))
			defer srv.Close()

			e := NewQueryEmbedder(srv.URL+"/v1", "s", 0, 4)
			err := e.Ready(context.Background())
			if tc.wantReady && err != nil {
				t.Fatalf("Ready = %v, want ready", err)
			}
			if !tc.wantReady {
				if !errors.Is(err, ErrEmbeddingsUnauthorized) {
					t.Fatalf("Ready = %v, want ErrEmbeddingsUnauthorized", err)
				}
				// The cached verdict keeps failing readiness inside the retry window.
				if err := e.Ready(context.Background()); !errors.Is(err, ErrEmbeddingsUnauthorized) {
					t.Fatalf("second Ready = %v, want ErrEmbeddingsUnauthorized", err)
				}
			}
		})
	}
}

func TestQueryEmbedderTrustsPerResponseCollection(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		if r.URL.Path == "/v1/info" {
			// The profile the gateway had at startup...
			_, _ = io.WriteString(w, strings.ReplaceAll(gatewayInfoBody, "0a1b2c3d", "11111111"))
			return
		}
		// ...and the one it answers with after a mid-flight profile change.
		_, _ = io.WriteString(w, gatewayQueryBody)
	}))
	defer srv.Close()

	var logs bytes.Buffer
	e := NewQueryEmbedder(srv.URL+"/v1", "", 0, 4).WithLogger(slog.New(slog.NewTextHandler(&logs, nil)))
	if _, err := e.RefreshInfo(context.Background()); err != nil {
		t.Fatal(err)
	}
	qv, err := e.EmbedQuery(context.Background(), "q")
	if err != nil {
		t.Fatal(err)
	}
	if qv.Collection != "raggie_chunks_d1024_0a1b2c3d" {
		t.Fatalf("collection = %q, want the per-response value", qv.Collection)
	}
	if _, ok := e.Info(); ok {
		t.Fatal("a stale cached profile must be dropped so readiness refetches it")
	}
	if !strings.Contains(logs.String(), "collection changed") {
		t.Fatalf("expected a collection-change warning, got: %s", logs.String())
	}
}

func TestRerankerSendsInternalBearer(t *testing.T) {
	var auth string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		auth = r.Header.Get("Authorization")
		_, _ = io.WriteString(w, `{"results":[{"index":0,"score":0.9}]}`)
	}))
	defer srv.Close()

	if _, err := NewReranker(srv.URL+"/v1", "internal-secret", 0, 4).Rerank(context.Background(), "q", []string{"a"}, 1); err != nil {
		t.Fatal(err)
	}
	if auth != "Bearer internal-secret" {
		t.Fatalf("Authorization = %q", auth)
	}
}

func TestRerankerTimeoutKnob(t *testing.T) {
	if got := NewReranker("http://unused", "", 0, 1).http.Timeout; got != DefaultRerankTimeout {
		t.Fatalf("default rerank timeout = %s, want %s", got, DefaultRerankTimeout)
	}
	if DefaultRerankTimeout != 5*time.Second {
		t.Fatalf("DefaultRerankTimeout = %s, want 5s", DefaultRerankTimeout)
	}
	if got := NewReranker("http://unused", "", 750*time.Millisecond, 1).http.Timeout; got != 750*time.Millisecond {
		t.Fatalf("configured rerank timeout = %s", got)
	}
}

func TestRerankerCountsAndThrottlesFailOpen(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusBadGateway)
	}))
	defer srv.Close()

	var logs bytes.Buffer
	r := NewReranker(srv.URL+"/v1", "", 0, 4).WithLogger(slog.New(slog.NewTextHandler(&logs, nil)))
	for i := 0; i < 3; i++ {
		if _, err := r.Rerank(context.Background(), "q", []string{"a", "b"}, 2); err == nil {
			t.Fatal("a 502 must surface as an error so the caller fails open")
		}
	}
	if got := r.FailOpenTotal(); got != 3 {
		t.Fatalf("FailOpenTotal = %d, want 3", got)
	}
	if n := strings.Count(logs.String(), "rerank failed open"); n != 1 {
		t.Fatalf("fail-open warnings logged %d times, want 1 (rate-limited): %s", n, logs.String())
	}
}

func TestRerankerDoesNotCountCallerCancellation(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusBadGateway)
	}))
	defer srv.Close()

	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	r := NewReranker(srv.URL+"/v1", "", 0, 4)
	if _, err := r.Rerank(ctx, "q", []string{"a", "b"}, 2); err == nil {
		t.Fatal("a cancelled request must error")
	}
	if got := r.FailOpenTotal(); got != 0 {
		t.Fatalf("FailOpenTotal = %d; an abandoned request is not a reranker failure", got)
	}
}
