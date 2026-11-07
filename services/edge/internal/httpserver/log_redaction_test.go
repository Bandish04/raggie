// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"bytes"
	"context"
	"errors"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"

	"github.com/alicangunduz/raggie/services/edge/internal/config"
	"github.com/alicangunduz/raggie/services/edge/internal/ports"
	"github.com/alicangunduz/raggie/services/edge/internal/ports/mock"
	"github.com/alicangunduz/raggie/services/edge/internal/rag"
)

// secretQuery is a user message containing PII that must never reach logs.
const secretQuery = "Ayse Yilmaz TCKN 12345678901 maas bordrosu ayse@example.com" // #nosec G101 -- fake PII test input

type failingVectorStore struct{}

func (failingVectorStore) Search(context.Context, []string, ports.QueryVectors, int) ([]ports.Chunk, error) {
	return nil, errors.New("qdrant down")
}

type failingChat struct{}

func (failingChat) Stream(context.Context, ports.ChatRequest) (<-chan ports.ChatChunk, error) {
	return nil, errors.New("upstream 500")
}

// syncBuffer is a goroutine-safe log sink.
type syncBuffer struct {
	mu  sync.Mutex
	buf bytes.Buffer
}

func (b *syncBuffer) Write(p []byte) (int, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.buf.Write(p)
}

func (b *syncBuffer) String() string {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.buf.String()
}

func TestChatFailureLogsNeverContainQueryText(t *testing.T) {
	cases := map[string]struct {
		cfg  config.Config
		deps Deps
	}{
		"retrieval failure": {
			cfg:  testCfg(),
			deps: hotPath(Deps{RAG: rag.New(mock.QueryEmbedder{Dim: 8}, failingVectorStore{}), Chat: mock.ChatProvider{}}),
		},
		"legacy upstream failure": {
			cfg:  testCfg(),
			deps: hotPath(Deps{RAG: rag.New(mock.QueryEmbedder{Dim: 8}, mock.VectorStore{}), Chat: failingChat{}}),
		},
		"unified upstream failure": {
			cfg:  config.Config{Port: "8080", LogLevel: "error", AgentUnifiedLoop: true},
			deps: hotPath(Deps{RAG: rag.New(mock.QueryEmbedder{Dim: 8}, mock.VectorStore{}), Chat: failingChat{}}),
		},
	}
	for name, tc := range cases {
		t.Run(name, func(t *testing.T) {
			var logs syncBuffer
			logger := slog.New(slog.NewJSONHandler(&logs, &slog.HandlerOptions{Level: slog.LevelDebug}))
			srv := New(tc.cfg, logger, tc.deps)
			body := `{"workspace_id":"ws1","message":"` + secretQuery + `","deep_search":true}`
			req := httptest.NewRequest(http.MethodPost, "/api/v1/chat/stream", strings.NewReader(body))
			rec := httptest.NewRecorder()
			srv.Handler.ServeHTTP(rec, req)

			out := logs.String()
			if out == "" {
				t.Fatal("expected some log output")
			}
			for _, fragment := range []string{"12345678901", "ayse@example.com", "Ayse Yilmaz"} {
				if strings.Contains(out, fragment) {
					t.Fatalf("log leaked user query fragment %q:\n%s", fragment, out)
				}
			}
		})
	}
}

func TestWebSearchFailureLogsNeverContainQuery(t *testing.T) {
	var logs syncBuffer
	logger := slog.New(slog.NewJSONHandler(&logs, nil))
	deps := Deps{Web: &mock.WebSearcher{Err: errors.New("brave 500")}}
	runWebResearch(context.Background(), deps, logger, secretQuery, []string{secretQuery},
		ports.WebResearchOptions{MaxResults: 5, TopN: 5})
	deepSearch(context.Background(), deps, logger, []string{secretQuery}, 5, 5)
	out := logs.String()
	if !strings.Contains(out, "web search failed") || !strings.Contains(out, "deep sub-query search failed") {
		t.Fatalf("expected both failure logs, got:\n%s", out)
	}
	if strings.Contains(out, "12345678901") {
		t.Fatalf("web search log leaked the query:\n%s", out)
	}
}

func TestRunTaskFailureLogsNeverContainPrompt(t *testing.T) {
	var logs syncBuffer
	logger := slog.New(slog.NewJSONHandler(&logs, nil))
	cfg := config.Config{InternalAPISecret: "s3cr3t", RetrieveCandidateK: 4, RetrieveContextK: 2}
	srv := New(cfg, logger, hotPath(Deps{
		RAG:  rag.New(mock.QueryEmbedder{Dim: 8}, failingVectorStore{}),
		Chat: mock.ChatProvider{},
	}))
	req := httptest.NewRequest(http.MethodPost, "/api/v1/internal/run-task",
		strings.NewReader(`{"workspace_id":"w1","user_id":"u1","prompt":"`+secretQuery+`"}`))
	req.Header.Set("X-Internal-Secret", "s3cr3t")
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusBadGateway {
		t.Fatalf("expected 502, got %d", rec.Code)
	}
	if out := logs.String(); strings.Contains(out, "12345678901") {
		t.Fatalf("run-task log leaked the prompt:\n%s", out)
	}
}

func TestQueryLogAttrIsStableAndRedacted(t *testing.T) {
	a, b := queryLogAttr(secretQuery), queryLogAttr(secretQuery)
	if a.String() != b.String() {
		t.Fatalf("query hash must be stable for correlation: %s vs %s", a, b)
	}
	if strings.Contains(a.String(), "12345678901") {
		t.Fatalf("query attr must not contain the text: %s", a)
	}
	if !strings.Contains(a.String(), "len=") || !strings.Contains(a.String(), "sha256=") {
		t.Fatalf("query attr should carry len + sha256 prefix: %s", a)
	}
}
