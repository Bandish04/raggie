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
	"time"

	"github.com/alicangunduz/raggie/services/edge/internal/agent"
	"github.com/alicangunduz/raggie/services/edge/internal/config"
	"github.com/alicangunduz/raggie/services/edge/internal/mcp"
	"github.com/alicangunduz/raggie/services/edge/internal/ports"
	"github.com/alicangunduz/raggie/services/edge/internal/ports/mock"
	"github.com/alicangunduz/raggie/services/edge/internal/rag"
	"github.com/alicangunduz/raggie/services/edge/internal/widgetauth"
)

// With AGENT_UNIFIED_LOOP on and NO tool enabled, a turn is exactly ONE Stream
// call — pure documents RAG, with the same sources + content + DONE as legacy.
func TestUnifiedLoopNoToolsSingleStream(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	queryEmbedder := mock.QueryEmbedder{Dim: 8}
	vs := mock.VectorStore{Chunks: []ports.Chunk{
		{DocumentID: "d1", Filename: "geo.txt", Text: "Paris is the capital of France.", Score: 0.92},
	}}
	deps := Deps{RAG: rag.New(queryEmbedder, vs), Chat: mock.ChatProvider{Response: "Paris."}}
	deps = hotPath(deps)
	cfg := config.Config{Port: "8080", LogLevel: "error", AgentUnifiedLoop: true, AgentMaxIterations: 4}
	srv := New(cfg, logger, deps)

	body := `{"workspace_id":"ws1","message":"What is the capital of France?"}`
	req := httptest.NewRequest(http.MethodPost, "/api/v1/chat/stream", strings.NewReader(body))
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rec.Code)
	}
	out := rec.Body.String()
	if !strings.Contains(out, "event: sources") || !strings.Contains(out, "Paris is the capital of France.") {
		t.Fatalf("expected a sources event with the document chunk, got:\n%s", out)
	}
	if !strings.Contains(out, "Paris.") || !strings.Contains(out, "[DONE]") {
		t.Fatalf("expected streamed content + terminal DONE, got:\n%s", out)
	}
	// No tools enabled ⇒ NO tool events.
	if strings.Contains(out, "event: tool_call") || strings.Contains(out, "event: tool_result") {
		t.Fatalf("expected NO tool events with no mode enabled, got:\n%s", out)
	}
	if strings.Count(out, "event: sources") != 1 {
		t.Fatalf("expected one authoritative sources event, got:\n%s", out)
	}
	if !strings.Contains(out, `"type":"doc"`) {
		t.Fatalf("expected normalized document source cards, got:\n%s", out)
	}
}

func TestCombinedSourcesKeepCitationOrder(t *testing.T) {
	docs := []ports.Chunk{
		{DocumentID: "d1", Filename: "policy.pdf", Text: "Internal policy", Score: 0.9},
		{DocumentID: "d2", Filename: "guide.pdf", Text: "Internal guide", Score: 0.8},
	}
	web := []ports.WebResult{
		{Title: "Official source", URL: "https://example.com/official", Snippet: "Web evidence"},
	}

	cards := combinedSourceCards(docs, web)
	if len(cards) != 3 {
		t.Fatalf("expected 3 source cards, got %d", len(cards))
	}
	if cards[0]["type"] != "doc" || cards[2]["type"] != "web" {
		t.Fatalf("expected document cards before web cards, got %+v", cards)
	}
	context := webEvidenceContextBlockFrom(web, len(docs)+1)
	if !strings.Contains(context, "[3]") || strings.Contains(context, "[1]") {
		t.Fatalf("expected web citation numbering to start at 3, got %q", context)
	}
}

// With AGENT_UNIFIED_LOOP on, mcp_tools=true and a connected jira gate, the
// unified loop seeds MCP tools, invokes them, and emits tool_call/tool_result.
func TestUnifiedLoopMCPToolPath(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	chat := &toolLoopChatProvider{} // from chat_tools_test.go: tool call then answer
	tools := &fakeToolProvider{}    // jira_search
	queryEmbedder := mock.QueryEmbedder{Dim: 8}
	vs := mock.VectorStore{Chunks: []ports.Chunk{
		{DocumentID: "d1", Filename: "doc.txt", Text: "context", Score: 0.9},
	}}
	deps := Deps{
		RAG:      rag.New(queryEmbedder, vs),
		Chat:     chat,
		MCP:      tools,
		JiraGate: stubJiraGate{has: true},
		WSInfo:   fakeWS{typ: "INTERNAL", access: true}, // MCP requires an authenticated internal user
	}
	deps = hotPath(deps)
	// MCP tools are only advertised to a model in TOOL_MODELS; the request sends no
	// model override, so the resolved model is cfg.ChatModel — opt it into tools.
	cfg := config.Config{
		Port: "8080", LogLevel: "error", AgentUnifiedLoop: true, AgentMaxIterations: 4,
		ChatModel: "gpt-oss-120b", ToolModels: map[string]bool{"gpt-oss-120b": true},
		JWTSecret: "jwt-test-secret",
	}
	srv := New(cfg, logger, deps)

	body := `{"workspace_id":"ws1","message":"open issues?","mcp_tools":true}`
	req := httptest.NewRequest(http.MethodPost, "/api/v1/chat/stream", strings.NewReader(body))
	req.Header.Set("Authorization", "Bearer "+adminToken(t, "STAFF", "u1"))
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rec.Code)
	}
	out := rec.Body.String()
	if !tools.called.Load() {
		t.Fatal("expected the MCP tool to be invoked in the unified loop")
	}
	if chat.calls.Load() != 2 {
		t.Fatalf("expected 2 LLM turns (tool call + final), got %d", chat.calls.Load())
	}
	for _, want := range []string{"event: tool_call", "event: tool_result", "You have 2 open issues.", "[DONE]"} {
		if !strings.Contains(out, want) {
			t.Fatalf("expected %q in unified MCP output, got:\n%s", want, out)
		}
	}
}

// With AGENT_UNIFIED_LOOP on but mcp_tools NOT set, MCP tools are NOT seeded even
// when a jira integration is connected (opt-in only).
func TestUnifiedLoopMCPOptInRequired(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	chat := &toolLoopChatProvider{}
	tools := &fakeToolProvider{}
	queryEmbedder := mock.QueryEmbedder{Dim: 8}
	vs := mock.VectorStore{Chunks: []ports.Chunk{{DocumentID: "d1", Filename: "d.txt", Text: "x", Score: 0.9}}}
	deps := Deps{
		RAG:      rag.New(queryEmbedder, vs),
		Chat:     chat,
		MCP:      tools,
		JiraGate: stubJiraGate{has: true},
	}
	deps = hotPath(deps)
	// Model supports tools, so the ONLY reason MCP stays off here is the missing
	// mcp_tools opt-in (the behaviour under test).
	cfg := config.Config{
		Port: "8080", LogLevel: "error", AgentUnifiedLoop: true, AgentMaxIterations: 4,
		ChatModel: "gpt-oss-120b", ToolModels: map[string]bool{"gpt-oss-120b": true},
	}
	srv := New(cfg, logger, deps)

	body := `{"workspace_id":"ws1","message":"hi"}` // no mcp_tools
	req := httptest.NewRequest(http.MethodPost, "/api/v1/chat/stream", strings.NewReader(body))
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)

	if tools.called.Load() {
		t.Fatal("MCP tool must NOT be invoked without mcp_tools opt-in")
	}
	if chat.calls.Load() != 1 {
		t.Fatalf("expected exactly 1 LLM turn without tools, got %d", chat.calls.Load())
	}
}

// recordingChatProvider answers in one turn and records whether the request
// carried tools / a tool_choice — used to prove a non-tool model is never sent a
// tools payload (so it can't 4xx mid-stream).
type recordingChatProvider struct {
	calls      atomic.Int32
	sawTools   atomic.Bool
	lastChoice atomic.Value // string
}

func (p *recordingChatProvider) Stream(ctx context.Context, req ports.ChatRequest) (<-chan ports.ChatChunk, error) {
	p.calls.Add(1)
	if len(req.Tools) > 0 {
		p.sawTools.Store(true)
	}
	p.lastChoice.Store(req.ToolChoice)
	ch := make(chan ports.ChatChunk)
	go func() {
		defer close(ch)
		ch <- ports.ChatChunk{Delta: "Grounded answer."}
		ch <- ports.ChatChunk{Done: true, FinishReason: "stop", Usage: &ports.Usage{CompletionTokens: 3}}
	}()
	return ch, nil
}

// A model NOT in TOOL_MODELS, even with mcp_tools=true and a connected jira, must
// NEVER receive a tools/tool_choice payload — MCP becomes a no-op (not an error)
// and the turn still answers in exactly ONE Stream call with documents grounding.
func TestUnifiedLoopNonToolModelSkipsMCP(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	chat := &recordingChatProvider{}
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
	}
	deps = hotPath(deps)
	// The resolved model ("legacy-no-tools") is NOT in ToolModels ⇒ no tools sent.
	cfg := config.Config{
		Port: "8080", LogLevel: "error", AgentUnifiedLoop: true, AgentMaxIterations: 4,
		ChatModel: "legacy-no-tools", ToolModels: map[string]bool{"gpt-oss-120b": true},
	}
	srv := New(cfg, logger, deps)

	body := `{"workspace_id":"ws1","message":"open issues?","mcp_tools":true}`
	req := httptest.NewRequest(http.MethodPost, "/api/v1/chat/stream", strings.NewReader(body))
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rec.Code)
	}
	if tools.called.Load() {
		t.Fatal("MCP tool must NOT be invoked on a non-tool model")
	}
	if chat.sawTools.Load() {
		t.Fatal("a non-tool model must NEVER receive a tools payload")
	}
	if c, _ := chat.lastChoice.Load().(string); c != "" {
		t.Fatalf("a non-tool model must never receive a tool_choice, got %q", c)
	}
	if chat.calls.Load() != 1 {
		t.Fatalf("expected exactly 1 Stream call (no agentic loop), got %d", chat.calls.Load())
	}
	out := rec.Body.String()
	if !strings.Contains(out, "Grounded answer.") || !strings.Contains(out, "[DONE]") {
		t.Fatalf("expected the turn to still answer with grounding + DONE, got:\n%s", out)
	}
}

type webToolLoopChatProvider struct {
	calls atomic.Int32
}

func (p *webToolLoopChatProvider) Stream(ctx context.Context, req ports.ChatRequest) (<-chan ports.ChatChunk, error) {
	n := p.calls.Add(1)
	ch := make(chan ports.ChatChunk)
	go func() {
		defer close(ch)
		if n == 1 {
			ch <- ports.ChatChunk{
				Done:         true,
				FinishReason: "tool_calls",
				ToolCalls: []ports.ToolCall{
					{ID: "web-1", Name: "web_search", Arguments: `{"query":"raggie tool calling"}`},
				},
			}
			return
		}
		ch <- ports.ChatChunk{Delta: "Final answer with web evidence [2]."}
		ch <- ports.ChatChunk{Done: true, FinishReason: "stop"}
	}()
	return ch, nil
}

func TestWebSearchNativeToolAddsSourcesAndAudit(t *testing.T) {
	chat := &webToolLoopChatProvider{}
	web := &mock.WebSearcher{Default: []ports.WebResult{{
		Title: "Raggie tools", URL: "https://example.test/tools", Snippet: "Tool calling evidence",
	}}}
	deps := Deps{Chat: chat, Web: web}
	deps = hotPath(deps)
	cfg := config.Config{WebSearchTopN: 5, WebSearchReadTopN: 5}
	sourceState := newToolSourceState(documentSourceCards([]ports.Chunk{{
		DocumentID: "d1", Filename: "doc.txt", Text: "doc evidence", Score: 0.9,
	}}))
	reg := agent.NewRegistry()
	var events []string
	emit := func(event string, data []byte) {
		events = append(events, event+"|"+string(data))
	}
	addWebResearchTools(reg, deps, discardLogger(), cfg, chatStreamRequest{
		Message: "Use the web",
		Model:   "tool-model",
	}, sourceState, emit, true, false)

	res := agent.RunWithTools(context.Background(), reg, agent.RunParams{
		Chat:          chat,
		Messages:      []ports.Message{{Role: ports.RoleUser, Content: "Use the web"}},
		MaxIterations: 3,
	}, emit)

	if res.Answer != "Final answer with web evidence [2]." || !res.Completed {
		t.Fatalf("unexpected result: %+v", res)
	}
	if q := web.AskedQueries(); len(q) != 1 || q[0] != "raggie tool calling" {
		t.Fatalf("expected supplied web tool query to be used, got %v", q)
	}
	if len(res.ToolExecutions) != 1 || res.ToolExecutions[0].Kind != toolKindWeb || !res.ToolExecutions[0].OK {
		t.Fatalf("expected successful web tool audit, got %+v", res.ToolExecutions)
	}
	joined := strings.Join(events, "\n")
	if !strings.Contains(joined, "tool_call|") || !strings.Contains(joined, "web_search") {
		t.Fatalf("expected web_search tool_call event, got:\n%s", joined)
	}
	if !strings.Contains(joined, "sources|") || !strings.Contains(string(sourceState.JSON()), "https://example.test/tools") {
		t.Fatalf("expected updated web sources, events:\n%s\njson=%s", joined, sourceState.JSON())
	}
}

func TestFilterAllowedMCPToolsSkipsReservedNativeNames(t *testing.T) {
	got := filterAllowedMCPTools([]mcp.ToolDef{
		{Name: "web_search"},
		{Name: "jira_search"},
		{Name: "search_tools"},
		{Name: "deep_research"},
	}, nil, false)
	if len(got) != 1 || got[0].Name != "jira_search" {
		t.Fatalf("expected only non-reserved jira_search, got %+v", got)
	}
}

// ── Admin MCP capabilities endpoint ───────────────────────────────────────────

// versionedStub implements mcp.VersionedProvider for the admin endpoint test.
type versionedStub struct {
	defs    []mcp.ToolDef
	version string
	err     error
}

func (s versionedStub) ListTools(ctx context.Context) ([]mcp.ToolDef, error) { return s.defs, s.err }
func (s versionedStub) CallTool(ctx context.Context, name string, args json.RawMessage) (string, bool, error) {
	return "", false, nil
}
func (s versionedStub) ProtocolVersion() string { return s.version }
func (s versionedStub) HealthCheck(ctx context.Context) (mcp.HealthStatus, error) {
	if s.err != nil {
		return mcp.HealthStatus{}, s.err
	}
	return mcp.HealthStatus{Version: s.version, ToolCount: len(s.defs), Latency: 3 * time.Millisecond}, nil
}
func (s versionedStub) RefreshTools(ctx context.Context) ([]mcp.ToolDef, error) { return s.defs, s.err }

// adminTokenFor mints an aud=admin HS256 token with the given role for testing.
func adminTokenFor(t *testing.T, secret, role string) string {
	t.Helper()
	tok, err := widgetauth.SignHS256(secret, map[string]any{
		"aud": "admin", "type": "access", "role": role, "sub": "admin-1", "org_id": "org-1",
		"exp": time.Now().Add(time.Hour).Unix(),
	})
	if err != nil {
		t.Fatalf("make admin token: %v", err)
	}
	return tok
}

func TestAdminMCPCapabilitiesOK(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	deps := mockDeps()
	deps.MCP = versionedStub{
		version: "2025-03-26",
		defs:    []mcp.ToolDef{{Name: "jira_search", Description: "Search Jira"}},
	}
	cfg := config.Config{Port: "8080", LogLevel: "error", JWTSecret: "test-secret"}
	srv := New(cfg, logger, deps)

	req := httptest.NewRequest(http.MethodGet, "/api/v1/admin/mcp/capabilities?provider=jira", nil)
	req.Header.Set("Authorization", "Bearer "+adminTokenFor(t, "test-secret", "SUPER_ADMIN"))
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", rec.Code, rec.Body.String())
	}
	var resp mcpCapabilityResponse
	if err := json.Unmarshal(rec.Body.Bytes(), &resp); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if !resp.Enabled || resp.Status != "ok" {
		t.Fatalf("expected enabled+ok, got enabled=%v status=%q", resp.Enabled, resp.Status)
	}
	if resp.ProtocolVersion != "2025-03-26" {
		t.Fatalf("expected protocol version, got %q", resp.ProtocolVersion)
	}
	if len(resp.Tools) != 1 || resp.Tools[0].Name != "jira_search" {
		t.Fatalf("expected the jira_search tool, got %+v", resp.Tools)
	}
}

// MCP not wired ⇒ 200 with status "disabled" (fail-soft, never 503).
func TestAdminMCPCapabilitiesDisabled(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	deps := mockDeps() // no MCP
	cfg := config.Config{Port: "8080", LogLevel: "error", JWTSecret: "test-secret"}
	srv := New(cfg, logger, deps)

	req := httptest.NewRequest(http.MethodGet, "/api/v1/admin/mcp/capabilities", nil)
	req.Header.Set("Authorization", "Bearer "+adminTokenFor(t, "test-secret", "WORKSPACE_ADMIN"))
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200 (fail-soft), got %d", rec.Code)
	}
	var resp mcpCapabilityResponse
	_ = json.Unmarshal(rec.Body.Bytes(), &resp)
	if resp.Enabled || resp.Status != "disabled" {
		t.Fatalf("expected disabled, got enabled=%v status=%q", resp.Enabled, resp.Status)
	}
}

// A non-admin (STAFF) token is forbidden.
func TestAdminMCPCapabilitiesForbiddenForStaff(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	deps := mockDeps()
	deps.MCP = versionedStub{version: "2025-03-26"}
	cfg := config.Config{Port: "8080", LogLevel: "error", JWTSecret: "test-secret"}
	srv := New(cfg, logger, deps)

	req := httptest.NewRequest(http.MethodGet, "/api/v1/admin/mcp/capabilities", nil)
	req.Header.Set("Authorization", "Bearer "+adminTokenFor(t, "test-secret", "STAFF"))
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusForbidden {
		t.Fatalf("expected 403 for STAFF, got %d", rec.Code)
	}
}

// No bearer ⇒ 401.
func TestAdminMCPCapabilitiesUnauthorized(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	deps := mockDeps()
	cfg := config.Config{Port: "8080", LogLevel: "error", JWTSecret: "test-secret"}
	srv := New(cfg, logger, deps)

	req := httptest.NewRequest(http.MethodGet, "/api/v1/admin/mcp/capabilities", nil)
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401 without a token, got %d", rec.Code)
	}
}
