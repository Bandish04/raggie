// SPDX-License-Identifier: Apache-2.0

// LLM/RAG security suite (Faz 6b.4), deterministic and per-PR: mock LLM, fake
// tool provider and fake stores, no infrastructure. Run every package's part
// with `go test -run LLMSec ./...`; the guard → test map is in
// tests/security/llm/README.md.
package httpserver

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"slices"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/alicangunduz/raggie/services/edge/internal/config"
	"github.com/alicangunduz/raggie/services/edge/internal/mcp"
	"github.com/alicangunduz/raggie/services/edge/internal/ports"
	"github.com/alicangunduz/raggie/services/edge/internal/ports/mock"
	"github.com/alicangunduz/raggie/services/edge/internal/rag"
	"github.com/alicangunduz/raggie/services/edge/internal/widgetauth"
)

// listCountingTools wraps fakeToolProvider and records tools/list calls, so a
// test can prove MCP was never even consulted.
type listCountingTools struct {
	fakeToolProvider
	lists atomic.Int32
}

func (l *listCountingTools) ListTools(ctx context.Context) ([]mcp.ToolDef, error) {
	l.lists.Add(1)
	return l.fakeToolProvider.ListTools(ctx)
}

func mcpTestCfg(unified bool) config.Config {
	cfg := widgetCfg()
	cfg.MCPMaxIterations = 4
	cfg.AgentMaxIterations = 4
	cfg.AgentUnifiedLoop = unified
	cfg.ChatModel = "gpt-oss-120b"
	cfg.ToolModels = map[string]bool{"gpt-oss-120b": true}
	return cfg
}

func mcpTestDeps(tools mcp.ToolProvider) Deps {
	vs := mock.VectorStore{Chunks: []ports.Chunk{{DocumentID: "d1", Filename: "d.txt", Text: "ctx", Score: 0.9}}}
	return Deps{
		RAG:      rag.New(mock.QueryEmbedder{Dim: 8}, vs),
		Chat:     &toolLoopChatProvider{},
		MCP:      tools,
		JiraGate: stubJiraGate{has: true},
	}
}

// An anonymous widget session must never reach MCP tools (they act with the
// org's integration credentials), even when it asks for them and the org has a
// connected Jira.
func TestLLMSecWidgetSessionNeverGetsMCPTools(t *testing.T) {
	for _, unified := range []bool{false, true} {
		tools := &listCountingTools{}
		deps := mcpTestDeps(tools)
		deps.WSInfo = fakeWS{typ: "EXTERNAL", cors: []string{"https://acme.example"}}
		srv := New(mcpTestCfg(unified), discardLogger(), deps)

		tok, _ := widgetauth.Mint("test-secret", "wsX", 30*time.Minute, time.Now())
		req := httptest.NewRequest(http.MethodPost, "/api/v1/chat/stream",
			strings.NewReader(`{"workspace_id":"wsX","message":"list jira issues","mcp_tools":true}`))
		req.Header.Set("Origin", "https://acme.example")
		req.Header.Set("Authorization", "Bearer "+tok)
		rec := httptest.NewRecorder()
		srv.Handler.ServeHTTP(rec, req)

		if rec.Code != http.StatusOK {
			t.Fatalf("unified=%v: expected 200, got %d", unified, rec.Code)
		}
		if tools.called.Load() || tools.lists.Load() != 0 {
			t.Fatalf("unified=%v: widget session reached MCP (called=%v lists=%d)",
				unified, tools.called.Load(), tools.lists.Load())
		}
		if strings.Contains(rec.Body.String(), "ISSUE-1") {
			t.Fatalf("unified=%v: MCP tool output leaked to widget:\n%s", unified, rec.Body.String())
		}
	}
}

// The unauthenticated hot-path mode (no workspace store wired) has no user
// identity, so MCP is unavailable there too. The chat itself must succeed, so
// the request really reaches the MCP decision instead of stopping earlier.
func TestLLMSecUnauthenticatedChatNeverGetsMCPTools(t *testing.T) {
	for _, unified := range []bool{false, true} {
		tools := &listCountingTools{}
		srv := New(mcpTestCfg(unified), discardLogger(), hotPath(mcpTestDeps(tools)))
		req := httptest.NewRequest(http.MethodPost, "/api/v1/chat/stream",
			strings.NewReader(`{"workspace_id":"ws1","message":"list jira issues","mcp_tools":true}`))
		rec := httptest.NewRecorder()
		srv.Handler.ServeHTTP(rec, req)
		if rec.Code != http.StatusOK || !strings.Contains(rec.Body.String(), "data: [DONE]") {
			t.Fatalf("unified=%v: expected a completed chat, got %d:\n%s", unified, rec.Code, rec.Body.String())
		}
		if tools.called.Load() || tools.lists.Load() != 0 {
			t.Fatalf("unified=%v: anonymous chat reached MCP (called=%v lists=%d)",
				unified, tools.called.Load(), tools.lists.Load())
		}
		if strings.Contains(rec.Body.String(), "ISSUE-1") {
			t.Fatalf("unified=%v: MCP tool output leaked to an anonymous chat:\n%s", unified, rec.Body.String())
		}
	}
}

// An authenticated INTERNAL user with access still gets MCP tools.
func TestLLMSecInternalUserGetsMCPTools(t *testing.T) {
	for _, unified := range []bool{false, true} {
		tools := &listCountingTools{}
		deps := mcpTestDeps(tools)
		deps.WSInfo = fakeWS{typ: "INTERNAL", access: true}
		srv := New(mcpTestCfg(unified), discardLogger(), deps)
		req := httptest.NewRequest(http.MethodPost, "/api/v1/chat/stream",
			strings.NewReader(`{"workspace_id":"wsX","message":"list jira issues","mcp_tools":true}`))
		req.Header.Set("Authorization", "Bearer "+adminToken(t, "STAFF", "u1"))
		rec := httptest.NewRecorder()
		srv.Handler.ServeHTTP(rec, req)
		if rec.Code != http.StatusOK || !tools.called.Load() {
			t.Fatalf("unified=%v: internal user should use MCP (code=%d called=%v)",
				unified, rec.Code, tools.called.Load())
		}
	}
}

func boolPtr(b bool) *bool { return &b }

// Write-capable MCP tools are hidden unless MCP_ALLOW_WRITE_TOOLS is on. A tool
// counts as read-only only when the server says so (readOnlyHint) or, absent
// annotations, when its name is a read verb with no write verb.
func TestLLMSecFilterHidesWriteToolsByDefault(t *testing.T) {
	defs := []mcp.ToolDef{
		{Name: "jira_search"},
		{Name: "jira_get_issue"},
		{Name: "confluence_search"},
		{Name: "jira_batch_get_changelogs"},
		{Name: "jira_create_issue"},
		{Name: "jira_update_issue"},
		{Name: "jira_transition_issue"},
		{Name: "jira_add_comment"},
		{Name: "jira_download_attachments"},
		{Name: "do_something"},                                  // unknown verb -> not provably read-only
		{Name: "annotated_reader", ReadOnlyHint: boolPtr(true)}, // server-declared read-only
		{Name: "get_but_writes", ReadOnlyHint: boolPtr(false)},  // explicit hint wins over name
		{Name: "list_and_wipe", DestructiveHint: boolPtr(true)}, // destructive never read-only
	}
	names := func(ds []mcp.ToolDef) string {
		out := make([]string, 0, len(ds))
		for _, d := range ds {
			out = append(out, d.Name)
		}
		return strings.Join(out, ",")
	}
	got := names(filterAllowedMCPTools(defs, nil, false))
	want := "jira_search,jira_get_issue,confluence_search,jira_batch_get_changelogs,annotated_reader"
	if got != want {
		t.Fatalf("read-only filter:\n got  %s\n want %s", got, want)
	}
	if all := filterAllowedMCPTools(defs, nil, true); len(all) != len(defs) {
		t.Fatalf("MCP_ALLOW_WRITE_TOOLS=true should expose every tool, got %s", names(all))
	}
}

// catalogTools is an MCP provider with an arbitrary catalog that records every
// executed call.
type catalogTools struct {
	defs  []mcp.ToolDef
	mu    sync.Mutex
	calls []string
}

func (c *catalogTools) ListTools(context.Context) ([]mcp.ToolDef, error) { return c.defs, nil }

func (c *catalogTools) CallTool(_ context.Context, name string, _ json.RawMessage) (string, bool, error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.calls = append(c.calls, name)
	return "result of " + name, false, nil
}

func (c *catalogTools) called(name string) bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	return slices.Contains(c.calls, name)
}

// scriptedChat answers the n-th Stream call with script[n] (a terminal chunk,
// e.g. a tool call) and every later call with a plain answer, recording all
// requests so a test can see exactly which tools the model was offered.
type scriptedChat struct {
	mu     sync.Mutex
	reqs   []ports.ChatRequest
	script []ports.ChatChunk
}

func (c *scriptedChat) Stream(_ context.Context, req ports.ChatRequest) (<-chan ports.ChatChunk, error) {
	c.mu.Lock()
	n := len(c.reqs)
	c.reqs = append(c.reqs, req)
	c.mu.Unlock()
	ch := make(chan ports.ChatChunk, 2)
	if n < len(c.script) {
		ch <- c.script[n]
	} else {
		ch <- ports.ChatChunk{Delta: "answer [1]"}
		ch <- ports.ChatChunk{Done: true, FinishReason: "stop"}
	}
	close(ch)
	return ch, nil
}

// offered is every tool name advertised to the model across all requests.
func (c *scriptedChat) offered() map[string]bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	out := map[string]bool{}
	for _, r := range c.reqs {
		for _, s := range r.Tools {
			out[s.Name] = true
		}
	}
	return out
}

func toolCall(name, args string) ports.ChatChunk {
	return ports.ChatChunk{Done: true, FinishReason: "tool_calls", ToolCalls: []ports.ToolCall{{ID: "c1", Name: name, Arguments: args}}}
}

func internalToolChat(t *testing.T, cfg config.Config, tools mcp.ToolProvider, chat ports.ChatProvider) *httptest.ResponseRecorder {
	t.Helper()
	deps := mcpTestDeps(tools)
	deps.Chat = chat
	deps.WSInfo = fakeWS{typ: "INTERNAL", access: true}
	srv := New(cfg, discardLogger(), deps)
	req := httptest.NewRequest(http.MethodPost, "/api/v1/chat/stream",
		strings.NewReader(`{"workspace_id":"wsX","message":"create a jira issue for this","mcp_tools":true}`))
	req.Header.Set("Authorization", "Bearer "+adminToken(t, "STAFF", "u1"))
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("chat: %d %s", rec.Code, rec.Body.String())
	}
	return rec
}

var mixedCatalog = []mcp.ToolDef{
	{Name: "jira_search"}, {Name: "jira_get_issue"},
	{Name: "jira_create_issue"}, {Name: "jira_add_comment"}, {Name: "jira_transition_issue"},
}

// What the MODEL is offered (not just the filter function): with
// MCP_ALLOW_WRITE_TOOLS=false no write-capable tool is ever advertised, on
// both loops; with it on they are.
func TestLLMSecModelIsOfferedReadOnlyToolsByDefault(t *testing.T) {
	writes := []string{"jira_create_issue", "jira_add_comment", "jira_transition_issue"}
	for _, unified := range []bool{false, true} {
		for _, allowWrite := range []bool{false, true} {
			chat := &scriptedChat{}
			cfg := mcpTestCfg(unified)
			cfg.MCPAllowWriteTools = allowWrite
			internalToolChat(t, cfg, &catalogTools{defs: mixedCatalog}, chat)
			offered := chat.offered()
			if !offered["jira_search"] || !offered["jira_get_issue"] {
				t.Fatalf("unified=%v write=%v: read tools not offered: %v", unified, allowWrite, offered)
			}
			for _, w := range writes {
				if offered[w] != allowWrite {
					t.Fatalf("unified=%v MCP_ALLOW_WRITE_TOOLS=%v: write tool %s offered=%v", unified, allowWrite, w, offered[w])
				}
			}
		}
	}
}

// A catalog too large to list directly is exposed through search_tools; the
// search can only ever reveal tools that passed the read-only policy.
func TestLLMSecLargeCatalogSearchNeverRevealsWriteTools(t *testing.T) {
	// Write tools first in provider order AND the best match for the query: if
	// the read-only policy ever stopped applying they would rank first in both
	// the initial reveal and the search result.
	var defs []mcp.ToolDef
	for i := 0; i < 20; i++ {
		defs = append(defs, mcp.ToolDef{Name: fmt.Sprintf("crm_create_record_%02d", i), Description: "Create or delete or update a CRM record"})
	}
	for i := 0; i < 60; i++ {
		defs = append(defs, mcp.ToolDef{Name: fmt.Sprintf("crm_get_record_%02d", i), Description: "Read a CRM record"})
	}
	for _, unified := range []bool{false, true} {
		chat := &scriptedChat{script: []ports.ChatChunk{toolCall("search_tools", `{"query":"create delete update record"}`)}}
		tools := &catalogTools{defs: defs}
		internalToolChat(t, mcpTestCfg(unified), tools, chat)
		offered := chat.offered()
		if !offered["search_tools"] || len(chat.reqs) < 2 {
			t.Fatalf("unified=%v: expected the search_tools flow (offered %d tools over %d requests)", unified, len(offered), len(chat.reqs))
		}
		for name := range offered {
			if strings.HasPrefix(name, "crm_create_record_") {
				t.Fatalf("unified=%v: search revealed write tool %s", unified, name)
			}
		}
	}
}

// A prompt-injected model may "call" a tool it was never offered; the loop
// must answer ok:false and never execute it.
func TestLLMSecUnofferedToolCallIsNeverExecuted(t *testing.T) {
	for _, unified := range []bool{false, true} {
		chat := &scriptedChat{script: []ports.ChatChunk{toolCall("jira_create_issue", `{"summary":"pwned"}`)}}
		tools := &catalogTools{defs: mixedCatalog}
		rec := internalToolChat(t, mcpTestCfg(unified), tools, chat)
		if tools.called("jira_create_issue") {
			t.Fatalf("unified=%v: an unoffered write tool was executed", unified)
		}
		if !strings.Contains(rec.Body.String(), `"ok":false`) {
			t.Fatalf("unified=%v: expected an ok:false tool_result, got:\n%s", unified, rec.Body.String())
		}
	}
}

// scopedWS is a workspace store with per-workspace type and membership.
type scopedWS struct {
	typ     map[string]string
	allowed map[string]bool
	cors    []string
}

func (s scopedWS) WorkspaceWidget(_ context.Context, id string) (string, []string, string, string, error) {
	typ, ok := s.typ[id]
	if !ok {
		return "", nil, "", "", errors.New("not found")
	}
	return typ, s.cors, "#000000", "ws", nil
}

func (s scopedWS) UserCanAccessWorkspace(_ context.Context, _, ws string) (bool, error) {
	return s.allowed[ws], nil
}

// searchRecorder records the workspace set of every vector search.
type searchRecorder struct {
	mu   sync.Mutex
	sets [][]string
}

func (r *searchRecorder) Search(_ context.Context, ws []string, _ ports.QueryVectors, _ int) ([]ports.Chunk, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.sets = append(r.sets, slices.Clone(ws))
	return []ports.Chunk{{DocumentID: "d", Filename: "f.md", Text: "x", Score: 0.9}}, nil
}

// Retrieval only ever searches workspaces the caller is authorized for: an
// internal user gets exactly the authorized set, an unauthorized member of the
// set fails the whole turn before any search, and a widget token is pinned to
// its own workspace whatever the body asks for.
func TestLLMSecRetrievalScopedToAuthorizedWorkspaces(t *testing.T) {
	ws := scopedWS{
		typ:     map[string]string{"int-a": "INTERNAL", "int-b": "INTERNAL", "int-c": "INTERNAL", "ext-a": "EXTERNAL", "ext-b": "EXTERNAL"},
		allowed: map[string]bool{"int-a": true, "int-b": true},
		cors:    []string{"https://acme.example"},
	}
	widgetTok, _ := widgetauth.Mint("test-secret", "ext-a", 30*time.Minute, time.Now())
	for _, tc := range []struct {
		name       string
		body       string
		auth       string
		origin     string
		wantStatus int
		wantSet    []string // nil = no search may happen
	}{
		{"internal user, authorized set", `{"workspace_id":"int-a","workspace_ids":["int-a","int-b"],"message":"q"}`,
			adminToken(t, "STAFF", "u1"), "", http.StatusOK, []string{"int-a", "int-b"}},
		{"internal user, one unauthorized workspace", `{"workspace_id":"int-a","workspace_ids":["int-a","int-c"],"message":"q"}`,
			adminToken(t, "STAFF", "u1"), "", http.StatusNotFound, nil},
		{"widget asks for another workspace too", `{"workspace_id":"ext-a","workspace_ids":["ext-a","ext-b","int-a"],"message":"q"}`,
			widgetTok, "https://acme.example", http.StatusOK, []string{"ext-a"}},
		{"widget token used for another workspace", `{"workspace_id":"ext-b","message":"q"}`,
			widgetTok, "https://acme.example", http.StatusUnauthorized, nil},
	} {
		t.Run(tc.name, func(t *testing.T) {
			rec := &searchRecorder{}
			deps := Deps{
				RAG:    rag.New(mock.QueryEmbedder{Dim: 8}, rec),
				Chat:   mock.ChatProvider{Response: "answer"},
				WSInfo: ws,
			}
			srv := New(widgetCfg(), discardLogger(), deps)
			req := httptest.NewRequest(http.MethodPost, "/api/v1/chat/stream", strings.NewReader(tc.body))
			req.Header.Set("Authorization", "Bearer "+tc.auth)
			if tc.origin != "" {
				req.Header.Set("Origin", tc.origin)
			}
			out := httptest.NewRecorder()
			srv.Handler.ServeHTTP(out, req)
			if out.Code != tc.wantStatus {
				t.Fatalf("status %d, want %d: %s", out.Code, tc.wantStatus, out.Body.String())
			}
			if tc.wantSet == nil {
				if len(rec.sets) != 0 {
					t.Fatalf("searched %v although the turn was refused", rec.sets)
				}
				return
			}
			if len(rec.sets) != 1 || !slices.Equal(rec.sets[0], tc.wantSet) {
				t.Fatalf("searched %v, want exactly %v", rec.sets, tc.wantSet)
			}
		})
	}
}
