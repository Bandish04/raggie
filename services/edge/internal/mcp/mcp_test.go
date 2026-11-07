// SPDX-License-Identifier: Apache-2.0

package mcp

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

// rpcEnvelope is the minimal request shape the fake server decodes.
type rpcEnvelope struct {
	ID     *int64          `json:"id"`
	Method string          `json:"method"`
	Params json.RawMessage `json:"params"`
}

// TestClientJSONTransport drives the full handshake + tools/list + tools/call
// against a fake server that replies with application/json bodies and assigns a
// session id on initialize that the client must echo back.
func TestClientJSONTransport(t *testing.T) {
	var sawSession string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		var env rpcEnvelope
		_ = json.Unmarshal(body, &env)

		// After initialize the client must carry the session id on every request.
		if env.Method != "initialize" {
			if got := r.Header.Get("Mcp-Session-Id"); got != "sess-123" {
				t.Errorf("method %s: missing/incorrect Mcp-Session-Id header: %q", env.Method, got)
			}
		}
		if got := r.Header.Get("Accept"); !strings.Contains(got, "application/json") || !strings.Contains(got, "text/event-stream") {
			t.Errorf("Accept header missing both content types: %q", got)
		}

		w.Header().Set("Content-Type", "application/json")
		switch env.Method {
		case "initialize":
			sawSession = "sess-123"
			w.Header().Set("Mcp-Session-Id", sawSession)
			writeResult(w, *env.ID, `{"protocolVersion":"2025-03-26","capabilities":{}}`)
		case "notifications/initialized":
			w.WriteHeader(http.StatusAccepted) // notification: no body
		case "tools/list":
			writeResult(w, *env.ID, `{"tools":[{"name":"jira_search","description":"Search","inputSchema":{"type":"object","properties":{"jql":{"type":"string"}}}}]}`)
		case "tools/call":
			writeResult(w, *env.ID, `{"isError":false,"content":[{"type":"text","text":"ISSUE-1: Fix login"},{"type":"text","text":"ISSUE-2: Add SSO"}]}`)
		default:
			t.Errorf("unexpected method %q", env.Method)
		}
	}))
	defer srv.Close()

	c := New(srv.URL, 4)
	ctx := context.Background()

	defs, err := c.ListTools(ctx)
	if err != nil {
		t.Fatalf("ListTools: %v", err)
	}
	if len(defs) != 1 || defs[0].Name != "jira_search" {
		t.Fatalf("expected 1 tool jira_search, got %+v", defs)
	}
	if !strings.Contains(string(defs[0].InputSchema), "jql") {
		t.Fatalf("schema not passed through: %s", defs[0].InputSchema)
	}

	text, isErr, err := c.CallTool(ctx, "jira_search", json.RawMessage(`{"jql":"project=ABC"}`))
	if err != nil {
		t.Fatalf("CallTool: %v", err)
	}
	if isErr {
		t.Fatalf("expected isError=false")
	}
	// Two text blocks concatenated with a newline.
	if text != "ISSUE-1: Fix login\nISSUE-2: Add SSO" {
		t.Fatalf("unexpected flattened text: %q", text)
	}
}

// TestClientSSETransport proves the client also reads a JSON-RPC response
// delivered inside an SSE (text/event-stream) body, skipping unrelated events.
func TestClientSSETransport(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		var env rpcEnvelope
		_ = json.Unmarshal(body, &env)

		switch env.Method {
		case "initialize":
			w.Header().Set("Content-Type", "application/json")
			writeResult(w, *env.ID, `{"capabilities":{}}`)
		case "notifications/initialized":
			w.WriteHeader(http.StatusAccepted)
		case "tools/call":
			// Reply as SSE: an unrelated event first, then the real response.
			w.Header().Set("Content-Type", "text/event-stream")
			w.WriteHeader(http.StatusOK)
			fmt.Fprint(w, "event: message\ndata: {\"jsonrpc\":\"2.0\",\"method\":\"log\",\"params\":{}}\n\n")
			fmt.Fprintf(w, "event: message\ndata: {\"jsonrpc\":\"2.0\",\"id\":%d,\"result\":{\"isError\":false,\"content\":[{\"type\":\"text\",\"text\":\"ok-from-sse\"}]}}\n\n", *env.ID)
		case "tools/list":
			w.Header().Set("Content-Type", "application/json")
			writeResult(w, *env.ID, `{"tools":[]}`)
		}
	}))
	defer srv.Close()

	c := New(srv.URL, 4)
	text, isErr, err := c.CallTool(context.Background(), "jira_get_issue", json.RawMessage(`{"issue_key":"ABC-1"}`))
	if err != nil {
		t.Fatalf("CallTool over SSE: %v", err)
	}
	if isErr || text != "ok-from-sse" {
		t.Fatalf("unexpected SSE result: text=%q isErr=%v", text, isErr)
	}
}

// TestCallToolIsError verifies a tool-level failure (isError=true) is surfaced
// without a transport error.
func TestCallToolIsError(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		var env rpcEnvelope
		_ = json.Unmarshal(body, &env)
		w.Header().Set("Content-Type", "application/json")
		switch env.Method {
		case "initialize":
			writeResult(w, *env.ID, `{}`)
		case "notifications/initialized":
			w.WriteHeader(http.StatusAccepted)
		case "tools/call":
			writeResult(w, *env.ID, `{"isError":true,"content":[{"type":"text","text":"permission denied"}]}`)
		}
	}))
	defer srv.Close()

	c := New(srv.URL, 4)
	text, isErr, err := c.CallTool(context.Background(), "jira_search", nil)
	if err != nil {
		t.Fatalf("transport error should be nil for a tool-level failure: %v", err)
	}
	if !isErr || text != "permission denied" {
		t.Fatalf("expected isError=true with message, got text=%q isErr=%v", text, isErr)
	}
}

func writeResult(w http.ResponseWriter, id int64, resultJSON string) {
	fmt.Fprintf(w, `{"jsonrpc":"2.0","id":%d,"result":%s}`, id, resultJSON)
}

// TestProtocolVersionCapturedAndHealthCheck proves the client surfaces the
// server-NEGOTIATED protocol version and a HealthCheck reports it + a tool count.
func TestProtocolVersionCapturedAndHealthCheck(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		var env rpcEnvelope
		_ = json.Unmarshal(body, &env)
		w.Header().Set("Content-Type", "application/json")
		switch env.Method {
		case "initialize":
			// Negotiate a DIFFERENT version than the one the client advertises.
			writeResult(w, *env.ID, `{"protocolVersion":"2024-11-05","capabilities":{}}`)
		case "notifications/initialized":
			w.WriteHeader(http.StatusAccepted)
		case "tools/list":
			writeResult(w, *env.ID, `{"tools":[{"name":"jira_search","description":"Search"}]}`)
		}
	}))
	defer srv.Close()

	c := New(srv.URL, 4)
	h, err := c.HealthCheck(context.Background())
	if err != nil {
		t.Fatalf("HealthCheck: %v", err)
	}
	if h.Version != "2024-11-05" {
		t.Fatalf("expected negotiated version 2024-11-05, got %q", h.Version)
	}
	if h.ToolCount != 1 {
		t.Fatalf("expected 1 tool, got %d", h.ToolCount)
	}
	if c.ProtocolVersion() != "2024-11-05" {
		t.Fatalf("ProtocolVersion() = %q", c.ProtocolVersion())
	}
}

// TestListToolsTTLCacheAndRefresh proves tools/list is cached (a second ListTools
// does not hit the server) and RefreshTools forces a re-fetch.
func TestListToolsTTLCacheAndRefresh(t *testing.T) {
	var listCalls int
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		var env rpcEnvelope
		_ = json.Unmarshal(body, &env)
		w.Header().Set("Content-Type", "application/json")
		switch env.Method {
		case "initialize":
			writeResult(w, *env.ID, `{"protocolVersion":"2025-03-26"}`)
		case "notifications/initialized":
			w.WriteHeader(http.StatusAccepted)
		case "tools/list":
			listCalls++
			writeResult(w, *env.ID, `{"tools":[{"name":"jira_search","description":"Search"}]}`)
		}
	}))
	defer srv.Close()

	c := New(srv.URL, 4)
	ctx := context.Background()
	if _, err := c.ListTools(ctx); err != nil {
		t.Fatalf("ListTools 1: %v", err)
	}
	if _, err := c.ListTools(ctx); err != nil {
		t.Fatalf("ListTools 2: %v", err)
	}
	if listCalls != 1 {
		t.Fatalf("expected the 2nd ListTools to hit the TTL cache (1 server call), got %d", listCalls)
	}
	if _, err := c.RefreshTools(ctx); err != nil {
		t.Fatalf("RefreshTools: %v", err)
	}
	if listCalls != 2 {
		t.Fatalf("expected RefreshTools to force a re-fetch (2 server calls), got %d", listCalls)
	}
}

// TestSessionExpiryReHandshake proves a 401 on a call resets the session and the
// client re-handshakes once, recovering transparently.
func TestSessionExpiryReHandshake(t *testing.T) {
	var inits, calls int
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		var env rpcEnvelope
		_ = json.Unmarshal(body, &env)
		switch env.Method {
		case "initialize":
			inits++
			w.Header().Set("Content-Type", "application/json")
			writeResult(w, *env.ID, `{"protocolVersion":"2025-03-26"}`)
		case "notifications/initialized":
			w.WriteHeader(http.StatusAccepted)
		case "tools/call":
			calls++
			if calls == 1 {
				// First call: pretend the session expired.
				http.Error(w, "session expired", http.StatusUnauthorized)
				return
			}
			w.Header().Set("Content-Type", "application/json")
			writeResult(w, *env.ID, `{"isError":false,"content":[{"type":"text","text":"recovered"}]}`)
		}
	}))
	defer srv.Close()

	c := New(srv.URL, 4)
	text, isErr, err := c.CallTool(context.Background(), "jira_search", json.RawMessage(`{}`))
	if err != nil {
		t.Fatalf("CallTool should recover via re-handshake, got err: %v", err)
	}
	if isErr || text != "recovered" {
		t.Fatalf("expected recovered result, got text=%q isErr=%v", text, isErr)
	}
	if inits != 2 {
		t.Fatalf("expected 2 handshakes (initial + re-handshake after 401), got %d", inits)
	}
	total, errs := c.Counters()
	if total != 1 {
		t.Fatalf("expected 1 CallTool counted, got total=%d", total)
	}
	_ = errs
}

func TestListToolsPagination(t *testing.T) {
	var cursors []string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		var env rpcEnvelope
		_ = json.Unmarshal(body, &env)
		w.Header().Set("Content-Type", "application/json")
		switch env.Method {
		case "initialize":
			writeResult(w, *env.ID, `{}`)
		case "notifications/initialized":
			w.WriteHeader(http.StatusAccepted)
		case "tools/list":
			var params struct {
				Cursor string `json:"cursor"`
			}
			_ = json.Unmarshal(env.Params, &params)
			cursors = append(cursors, params.Cursor)
			if params.Cursor == "" {
				writeResult(w, *env.ID, `{"tools":[{"name":"a"}],"nextCursor":"next"}`)
			} else {
				writeResult(w, *env.ID, `{"tools":[{"name":"b"}]}`)
			}
		}
	}))
	defer srv.Close()

	defs, err := New(srv.URL, 4).ListTools(context.Background())
	if err != nil {
		t.Fatalf("ListTools: %v", err)
	}
	if len(defs) != 2 || defs[0].Name != "a" || defs[1].Name != "b" {
		t.Fatalf("expected paginated tools a,b; got %+v", defs)
	}
	if strings.Join(cursors, ",") != ",next" {
		t.Fatalf("unexpected cursors: %v", cursors)
	}
}

func TestCallToolStructuredContentAndTruncation(t *testing.T) {
	long := strings.Repeat("x", maxToolResultRunes+100)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		var env rpcEnvelope
		_ = json.Unmarshal(body, &env)
		w.Header().Set("Content-Type", "application/json")
		switch env.Method {
		case "initialize":
			writeResult(w, *env.ID, `{}`)
		case "notifications/initialized":
			w.WriteHeader(http.StatusAccepted)
		case "tools/call":
			payload := map[string]any{
				"isError":           false,
				"structuredContent": map[string]any{"issue": "ABC-1"},
				"content":           []map[string]string{{"type": "text", "text": long}},
			}
			raw, _ := json.Marshal(payload)
			writeResult(w, *env.ID, string(raw))
		}
	}))
	defer srv.Close()

	text, isErr, err := New(srv.URL, 4).CallTool(context.Background(), "jira_search", json.RawMessage(`{}`))
	if err != nil || isErr {
		t.Fatalf("CallTool: text=%q isErr=%v err=%v", text, isErr, err)
	}
	if !strings.Contains(text, "Tool result truncated") {
		t.Fatalf("expected truncation note, got len=%d", len([]rune(text)))
	}
	if !strings.Contains(text, "structuredContent") {
		t.Fatalf("expected structuredContent to be flattened into tool text")
	}
}

func TestCallToolRejectsInvalidArgumentsBeforeRPC(t *testing.T) {
	var toolCalls int
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		var env rpcEnvelope
		_ = json.Unmarshal(body, &env)
		w.Header().Set("Content-Type", "application/json")
		switch env.Method {
		case "initialize":
			writeResult(w, *env.ID, `{}`)
		case "notifications/initialized":
			w.WriteHeader(http.StatusAccepted)
		case "tools/call":
			toolCalls++
			writeResult(w, *env.ID, `{"isError":false,"content":[{"type":"text","text":"should-not-run"}]}`)
		}
	}))
	defer srv.Close()

	_, _, err := New(srv.URL, 4).CallTool(context.Background(), "jira_search", json.RawMessage(`["bad"]`))
	if err == nil || !strings.Contains(err.Error(), "arguments must be a JSON object") {
		t.Fatalf("expected object-argument validation error, got %v", err)
	}
	if toolCalls != 0 {
		t.Fatalf("tools/call must not be sent for invalid args, got %d calls", toolCalls)
	}
}

// tools/list annotations (readOnlyHint / destructiveHint) are carried onto the
// ToolDef so the edge can hide write-capable tools by default.
func TestListToolsParsesAnnotations(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		var env rpcEnvelope
		_ = json.Unmarshal(body, &env)
		w.Header().Set("Content-Type", "application/json")
		switch env.Method {
		case "initialize":
			writeResult(w, *env.ID, `{"capabilities":{}}`)
		case "notifications/initialized":
			w.WriteHeader(http.StatusAccepted)
		case "tools/list":
			writeResult(w, *env.ID, `{"tools":[
				{"name":"reader","annotations":{"readOnlyHint":true}},
				{"name":"jira_get_issue","annotations":{"readOnlyHint":false,"destructiveHint":true}},
				{"name":"plain"}
			]}`)
		}
	}))
	defer srv.Close()

	defs, err := New(srv.URL, 4).ListTools(context.Background())
	if err != nil || len(defs) != 3 {
		t.Fatalf("ListTools: defs=%+v err=%v", defs, err)
	}
	if defs[0].ReadOnlyHint == nil || !*defs[0].ReadOnlyHint || !defs[0].IsReadOnly() {
		t.Fatalf("reader should be read-only: %+v", defs[0])
	}
	if defs[1].DestructiveHint == nil || !*defs[1].DestructiveHint || defs[1].IsReadOnly() {
		t.Fatalf("annotated destructive tool must not be read-only despite its name: %+v", defs[1])
	}
	if defs[2].ReadOnlyHint != nil || defs[2].IsReadOnly() {
		t.Fatalf("unannotated, non-read-verb tool must not be read-only: %+v", defs[2])
	}
}
