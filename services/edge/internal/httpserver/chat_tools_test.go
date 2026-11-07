// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"

	"github.com/alicangunduz/raggie/services/edge/internal/config"
	"github.com/alicangunduz/raggie/services/edge/internal/mcp"
	"github.com/alicangunduz/raggie/services/edge/internal/ports"
	"github.com/alicangunduz/raggie/services/edge/internal/ports/mock"
	"github.com/alicangunduz/raggie/services/edge/internal/rag"
)

// toolLoopChatProvider streams a tool-call turn on its FIRST call, then a normal
// answer on the SECOND — exercising one full agentic iteration.
type toolLoopChatProvider struct {
	calls       atomic.Int32
	sawToolMsgs atomic.Bool // recorded whether the 2nd request carried a role:"tool" message
}

func (p *toolLoopChatProvider) Stream(ctx context.Context, req ports.ChatRequest) (<-chan ports.ChatChunk, error) {
	n := p.calls.Add(1)
	// On the follow-up turn, confirm the loop fed back the tool result.
	if n == 2 {
		for _, m := range req.Messages {
			if m.Role == ports.RoleTool {
				p.sawToolMsgs.Store(true)
			}
		}
	}
	ch := make(chan ports.ChatChunk)
	go func() {
		defer close(ch)
		if n == 1 {
			// First turn: a bit of reasoning, then a tool call.
			ch <- ports.ChatChunk{Reasoning: "let me check jira"}
			ch <- ports.ChatChunk{
				Done:         true,
				FinishReason: "tool_calls",
				ToolCalls: []ports.ToolCall{
					{ID: "call-1", Name: "jira_search", Arguments: `{"jql":"project=ABC AND status=Open"}`},
				},
				Usage: &ports.Usage{CompletionTokens: 2},
			}
			return
		}
		// Second turn: the final answer.
		ch <- ports.ChatChunk{Delta: "You have 2 open issues."}
		ch <- ports.ChatChunk{Done: true, FinishReason: "stop", Usage: &ports.Usage{CompletionTokens: 5}}
	}()
	return ch, nil
}

// fakeToolProvider implements mcp.ToolProvider with a single jira_search tool.
type fakeToolProvider struct {
	called  atomic.Bool
	gotName string
	gotArgs string
}

func (f *fakeToolProvider) ListTools(ctx context.Context) ([]mcp.ToolDef, error) {
	return []mcp.ToolDef{{
		Name:        "jira_search",
		Description: "Search Jira issues with JQL.",
		InputSchema: json.RawMessage(`{"type":"object","properties":{"jql":{"type":"string"}}}`),
	}}, nil
}

func (f *fakeToolProvider) CallTool(ctx context.Context, name string, argsJSON json.RawMessage) (string, bool, error) {
	f.called.Store(true)
	f.gotName = name
	f.gotArgs = string(argsJSON)
	return "ISSUE-1: Fix login\nISSUE-2: Add SSO", false, nil
}

// stubJiraGate forces the per-org gate on/off without a database.
type stubJiraGate struct{ has bool }

func (s stubJiraGate) HasConnectedJira(ctx context.Context, workspaceID string) (bool, error) {
	return s.has, nil
}

func TestChatToolLoopEmitsEventsAndCallsTool(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	chat := &toolLoopChatProvider{}
	tools := &fakeToolProvider{}
	queryEmbedder := mock.QueryEmbedder{Dim: 8}
	vs := mock.VectorStore{Chunks: []ports.Chunk{
		{DocumentID: "d1", Filename: "doc.txt", Text: "Some doc context.", Score: 0.9},
	}}
	deps := Deps{
		RAG:      rag.New(queryEmbedder, vs),
		Chat:     chat,
		MCP:      tools,
		JiraGate: stubJiraGate{has: true},
		WSInfo:   fakeWS{typ: "INTERNAL", access: true}, // MCP requires an authenticated internal user
	}
	deps = hotPath(deps)
	cfg := config.Config{
		Port: "8080", LogLevel: "error", MCPMaxIterations: 4,
		ChatModel: "gpt-oss-120b", ToolModels: map[string]bool{"gpt-oss-120b": true},
		StreamReasoning: true, JWTSecret: "jwt-test-secret",
	}
	srv := New(cfg, logger, deps)

	body := `{"workspace_id":"ws1","message":"How many open issues are there?","mcp_tools":true}`
	req := httptest.NewRequest(http.MethodPost, "/api/v1/chat/stream", strings.NewReader(body))
	req.Header.Set("Authorization", "Bearer "+adminToken(t, "STAFF", "u1"))
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rec.Code)
	}
	out := rec.Body.String()

	if !tools.called.Load() {
		t.Fatal("expected the MCP tool to be called")
	}
	if tools.gotName != "jira_search" || !strings.Contains(tools.gotArgs, "project=ABC") {
		t.Fatalf("tool got unexpected name/args: %q %q", tools.gotName, tools.gotArgs)
	}
	if chat.calls.Load() != 2 {
		t.Fatalf("expected 2 LLM turns (tool call + final), got %d", chat.calls.Load())
	}
	if !chat.sawToolMsgs.Load() {
		t.Fatal("expected the 2nd LLM request to carry a role:tool result message")
	}
	// Live tool events present.
	if !strings.Contains(out, "event: tool_call") {
		t.Fatalf("expected an event: tool_call, got:\n%s", out)
	}
	if !strings.Contains(out, "event: tool_result") {
		t.Fatalf("expected an event: tool_result, got:\n%s", out)
	}
	// The tool_result carries a bounded preview + ok flag.
	if !strings.Contains(out, `"ok":true`) || !strings.Contains(out, "ISSUE-1") {
		t.Fatalf("expected tool_result with ok:true and a preview, got:\n%s", out)
	}
	// Reasoning relayed on the thinking channel.
	if !strings.Contains(out, "event: thinking") || !strings.Contains(out, "let me check jira") {
		t.Fatalf("expected thinking event with reasoning, got:\n%s", out)
	}
	// Final answer streamed as a bare data delta, plus terminal DONE.
	if !strings.Contains(out, "You have 2 open issues.") || !strings.Contains(out, "[DONE]") {
		t.Fatalf("expected final answer + DONE, got:\n%s", out)
	}
	// Ordering: the tool_call must precede the final answer delta.
	iCall := strings.Index(out, "event: tool_call")
	iAns := strings.Index(out, "You have 2 open issues.")
	if iCall < 0 || iAns < 0 || iCall > iAns {
		t.Fatalf("expected tool_call before final answer, got call=%d ans=%d", iCall, iAns)
	}
}

// Connected MCP integrations still require an explicit per-turn opt-in.
func TestChatToolsRequireOptIn(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	chat := &toolLoopChatProvider{}
	tools := &fakeToolProvider{}
	queryEmbedder := mock.QueryEmbedder{Dim: 8}
	vs := mock.VectorStore{Chunks: []ports.Chunk{
		{DocumentID: "d1", Filename: "d.txt", Text: "x", Score: 0.9},
	}}
	deps := Deps{
		RAG:      rag.New(queryEmbedder, vs),
		Chat:     chat,
		MCP:      tools,
		JiraGate: stubJiraGate{has: true},
	}
	deps = hotPath(deps)
	srv := New(config.Config{MCPMaxIterations: 4}, logger, deps)

	req := httptest.NewRequest(
		http.MethodPost,
		"/api/v1/chat/stream",
		strings.NewReader(`{"workspace_id":"ws1","message":"hi"}`),
	)
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)

	if tools.called.Load() {
		t.Fatal("tool must NOT be called without mcp_tools opt-in")
	}
	if chat.calls.Load() != 1 {
		t.Fatalf("expected one normal LLM turn, got %d", chat.calls.Load())
	}
}

// TestChatToolsDisabledWhenGateOff proves that with the gate OFF, NO tools are
// offered and the provider is called exactly once (legacy single-stream path).
func TestChatToolsDisabledWhenGateOff(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	chat := &toolLoopChatProvider{}
	tools := &fakeToolProvider{}
	queryEmbedder := mock.QueryEmbedder{Dim: 8}
	vs := mock.VectorStore{Chunks: []ports.Chunk{{DocumentID: "d1", Filename: "d.txt", Text: "x", Score: 0.9}}}
	deps := Deps{
		RAG:      rag.New(queryEmbedder, vs),
		Chat:     chat,
		MCP:      tools,
		JiraGate: stubJiraGate{has: false}, // org has NO connected jira
	}
	deps = hotPath(deps)
	cfg := config.Config{Port: "8080", LogLevel: "error", MCPMaxIterations: 4}
	srv := New(cfg, logger, deps)

	body := `{"workspace_id":"ws1","message":"hi"}`
	req := httptest.NewRequest(http.MethodPost, "/api/v1/chat/stream", strings.NewReader(body))
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rec.Code)
	}
	if tools.called.Load() {
		t.Fatal("tool must NOT be called when the gate is off")
	}
	// First turn returns tool_calls, but since tools are disabled the request has
	// no tools field; the fake still returns its n==1 script (tool_calls), which
	// the legacy path treats as a terminal Done with no content. The key assertion
	// is that there is exactly ONE provider call and no tool events.
	if chat.calls.Load() != 1 {
		t.Fatalf("expected exactly 1 LLM turn with tools disabled, got %d", chat.calls.Load())
	}
	out := rec.Body.String()
	if strings.Contains(out, "event: tool_call") || strings.Contains(out, "event: tool_result") {
		t.Fatalf("expected NO tool events with gate off, got:\n%s", out)
	}
}
