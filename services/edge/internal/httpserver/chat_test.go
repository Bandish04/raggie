// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"context"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/alicangunduz/raggie/services/edge/internal/config"
	"github.com/alicangunduz/raggie/services/edge/internal/ports"
	"github.com/alicangunduz/raggie/services/edge/internal/ports/mock"
	"github.com/alicangunduz/raggie/services/edge/internal/rag"
)

// reasoningChatProvider streams a reasoning chunk (chain-of-thought) before the
// answer content, mirroring the live provider, so the handler's `thinking` SSE
// path can be exercised. It also records the ReasoningEffort it received.
type reasoningChatProvider struct {
	gotEffort string
}

func (p *reasoningChatProvider) Stream(ctx context.Context, req ports.ChatRequest) (<-chan ports.ChatChunk, error) {
	p.gotEffort = req.ReasoningEffort
	ch := make(chan ports.ChatChunk)
	go func() {
		defer close(ch)
		out := []ports.ChatChunk{
			{Reasoning: "thinking about Paris"},
			{Delta: "Paris."},
		}
		for _, c := range out {
			select {
			case <-ctx.Done():
				return
			case ch <- c:
			}
		}
		ch <- ports.ChatChunk{Done: true, Usage: &ports.Usage{CompletionTokens: 1}}
	}()
	return ch, nil
}

func testCfg() config.Config {
	return config.Config{Port: "8080", LogLevel: "error"}
}

func mockDeps() Deps {
	queryEmbedder := mock.QueryEmbedder{Dim: 8}
	vs := mock.VectorStore{Chunks: []ports.Chunk{
		{DocumentID: "d1", Filename: "geo.txt", Text: "Paris is the capital of France.", Score: 0.92},
	}}
	return hotPath(Deps{RAG: rag.New(queryEmbedder, vs), Chat: mock.ChatProvider{Response: "Paris."}})
}

// hotPath opts test deps without WSInfo into the unauthenticated hot path,
// which production (cmd/edge) can never enable.
func hotPath(d Deps) Deps {
	d.unauthenticatedHotPath = true
	return d
}

func TestChatStreamSSE(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	srv := New(testCfg(), logger, mockDeps())

	body := `{"workspace_id":"ws1","message":"What is the capital of France?"}`
	req := httptest.NewRequest(http.MethodPost, "/api/v1/chat/stream", strings.NewReader(body))
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rec.Code)
	}
	out := rec.Body.String()
	if !strings.Contains(out, "event: sources") || !strings.Contains(out, "Paris is the capital of France.") {
		t.Fatalf("expected a sources event with the citation, got:\n%s", out)
	}
	if !strings.Contains(out, `"delta"`) || !strings.Contains(out, "Paris.") {
		t.Fatalf("expected streamed content deltas, got:\n%s", out)
	}
	if !strings.Contains(out, "[DONE]") {
		t.Fatalf("expected terminal [DONE], got:\n%s", out)
	}
}

func TestChatStreamReasoningChannel(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	chat := &reasoningChatProvider{}
	queryEmbedder := mock.QueryEmbedder{Dim: 8}
	vs := mock.VectorStore{Chunks: []ports.Chunk{
		{DocumentID: "d1", Filename: "geo.txt", Text: "Paris is the capital of France.", Score: 0.92},
	}}
	deps := Deps{RAG: rag.New(queryEmbedder, vs), Chat: chat}
	deps = hotPath(deps)
	cfg := config.Config{Port: "8080", LogLevel: "error", ReasoningEffort: "medium", StreamReasoning: true}
	srv := New(cfg, logger, deps)

	body := `{"workspace_id":"ws1","message":"What is the capital of France?","reasoning_effort":"high"}`
	req := httptest.NewRequest(http.MethodPost, "/api/v1/chat/stream", strings.NewReader(body))
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rec.Code)
	}
	out := rec.Body.String()

	// A valid per-request effort wins over the config default.
	if chat.gotEffort != "high" {
		t.Fatalf("expected per-request reasoning_effort=high, got %q", chat.gotEffort)
	}
	// The reasoning is relayed on the `thinking` channel...
	if !strings.Contains(out, "event: thinking") || !strings.Contains(out, "thinking about Paris") {
		t.Fatalf("expected a thinking event with the reasoning delta, got:\n%s", out)
	}
	// ...and the answer content still streams as bare data deltas.
	if !strings.Contains(out, "Paris.") || !strings.Contains(out, "[DONE]") {
		t.Fatalf("expected answer content + terminal DONE, got:\n%s", out)
	}
	// Ordering: sources, then thinking, then the answer content delta.
	iSrc := strings.Index(out, "event: sources")
	iThink := strings.Index(out, "event: thinking")
	iAns := strings.Index(out, `{"delta":"Paris."}`)
	if iSrc < 0 || iThink < 0 || iAns < 0 || !(iSrc < iThink && iThink < iAns) {
		t.Fatalf("expected order sources < thinking < answer, got src=%d think=%d ans=%d in:\n%s", iSrc, iThink, iAns, out)
	}
}

func TestChatStreamReasoningEffortDefaults(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	chat := &reasoningChatProvider{}
	queryEmbedder := mock.QueryEmbedder{Dim: 8}
	vs := mock.VectorStore{Chunks: []ports.Chunk{{DocumentID: "d1", Filename: "g.txt", Text: "x", Score: 0.9}}}
	deps := Deps{RAG: rag.New(queryEmbedder, vs), Chat: chat}
	deps = hotPath(deps)
	cfg := config.Config{Port: "8080", LogLevel: "error", ReasoningEffort: "medium"}
	srv := New(cfg, logger, deps)

	// No reasoning_effort in the body, and an invalid value, both fall back to cfg.
	for _, body := range []string{
		`{"workspace_id":"ws1","message":"hi"}`,
		`{"workspace_id":"ws1","message":"hi","reasoning_effort":"ultra"}`,
	} {
		chat.gotEffort = ""
		req := httptest.NewRequest(http.MethodPost, "/api/v1/chat/stream", strings.NewReader(body))
		rec := httptest.NewRecorder()
		srv.Handler.ServeHTTP(rec, req)
		if chat.gotEffort != "medium" {
			t.Fatalf("expected fallback to config default medium for body %q, got %q", body, chat.gotEffort)
		}
	}
}

func TestChatStreamRejectsEmptyRequest(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	srv := New(testCfg(), logger, mockDeps())

	req := httptest.NewRequest(http.MethodPost, "/api/v1/chat/stream", strings.NewReader(`{}`))
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected 400 for missing fields, got %d", rec.Code)
	}
}

func TestChatStreamUnconfiguredReturns503(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	srv := New(testCfg(), logger, Deps{}) // nil RAG/Chat

	req := httptest.NewRequest(http.MethodPost, "/api/v1/chat/stream",
		strings.NewReader(`{"workspace_id":"ws1","message":"hi"}`))
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("expected 503 when chat not configured, got %d", rec.Code)
	}
}

// With STREAM_REASONING unset (default) the raw chain-of-thought never reaches
// the client on either the legacy or the unified path; the answer still streams.
func TestChatStreamSuppressesReasoningByDefault(t *testing.T) {
	for _, unified := range []bool{false, true} {
		logger := slog.New(slog.NewTextHandler(io.Discard, nil))
		vs := mock.VectorStore{Chunks: []ports.Chunk{
			{DocumentID: "d1", Filename: "geo.txt", Text: "Paris is the capital of France.", Score: 0.92},
		}}
		deps := Deps{RAG: rag.New(mock.QueryEmbedder{Dim: 8}, vs), Chat: &reasoningChatProvider{}}
		deps = hotPath(deps)
		cfg := config.Config{Port: "8080", LogLevel: "error", AgentUnifiedLoop: unified}
		srv := New(cfg, logger, deps)

		req := httptest.NewRequest(http.MethodPost, "/api/v1/chat/stream",
			strings.NewReader(`{"workspace_id":"ws1","message":"capital?"}`))
		rec := httptest.NewRecorder()
		srv.Handler.ServeHTTP(rec, req)

		out := rec.Body.String()
		if strings.Contains(out, "event: thinking") || strings.Contains(out, "thinking about Paris") {
			t.Fatalf("unified=%v: reasoning leaked by default:\n%s", unified, out)
		}
		if !strings.Contains(out, "Paris.") || !strings.Contains(out, "[DONE]") {
			t.Fatalf("unified=%v: expected the answer to stream, got:\n%s", unified, out)
		}
	}
}
