// SPDX-License-Identifier: Apache-2.0

package llm

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"reflect"
	"testing"
	"time"

	"github.com/alicangunduz/raggie/services/edge/internal/ports"
)

func TestChatProviderUsesTimeoutFreeStreamingClient(t *testing.T) {
	c := NewChatProvider("http://unused", "k", "m", 256, 4)
	if c.http.Timeout != 0 {
		t.Fatalf("streaming client timeout = %s, want 0", c.http.Timeout)
	}
	if c.http.Transport != c.adminHTTP.Transport {
		t.Fatal("streaming and admin clients should share the tuned transport")
	}
}

func TestChatProviderReadyRequiresConfiguredModel(t *testing.T) {
	models := `{"data":[{"id":"other"},{"id":"configured"}]}`
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/models" {
			t.Fatalf("path = %q, want /models", r.URL.Path)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, models)
	}))
	defer srv.Close()

	c := NewChatProvider(srv.URL, "k", "configured", 256, 4)
	if err := c.Ready(context.Background()); err != nil {
		t.Fatalf("configured model should be ready: %v", err)
	}

	c.model = "missing"
	if err := c.Ready(context.Background()); err == nil {
		t.Fatal("missing configured model must fail readiness")
	}
}

func TestQueryEmbedderReadyUsesServiceRoot(t *testing.T) {
	var paths []string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		paths = append(paths, r.URL.Path)
		if r.URL.Path != "/readyz" {
			w.WriteHeader(http.StatusNotFound) // an older gateway without /v1/info
			return
		}
		w.WriteHeader(http.StatusOK)
	}))
	defer srv.Close()

	e := NewQueryEmbedder(srv.URL+"/v1", "k", 0, 4)
	if err := e.Ready(context.Background()); err != nil {
		t.Fatal(err)
	}
	if len(paths) == 0 || paths[0] != "/readyz" {
		t.Fatalf("readiness paths = %q, want the gateway /readyz first", paths)
	}
}

func TestQueryEmbedderDecodesResponseBeforeDraining(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/query" {
			t.Fatalf("path = %q, want /v1/query", r.URL.Path)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"dense":[0.25,0.5],"sparse":{"indices":[7,11],"values":[1,0.75]}}`)
	}))
	defer srv.Close()

	e := NewQueryEmbedder(srv.URL+"/v1", "k", 0, 4)
	qv, err := e.EmbedQuery(context.Background(), "test query")
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(qv.Dense, []float32{0.25, 0.5}) {
		t.Fatalf("dense = %#v", qv.Dense)
	}
	if !reflect.DeepEqual(qv.Sparse.Indices, []uint32{7, 11}) ||
		!reflect.DeepEqual(qv.Sparse.Values, []float32{1, 0.75}) {
		t.Fatalf("sparse = %#v", qv.Sparse)
	}
	// An older gateway omits collection/fingerprint: the caller falls back.
	if qv.Collection != "" || qv.Fingerprint != "" {
		t.Fatalf("legacy response collection/fingerprint = %q/%q, want empty", qv.Collection, qv.Fingerprint)
	}
}

func TestChatSeparatesReasoningAndContent(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		f, _ := w.(http.Flusher)
		write := func(s string) {
			_, _ = io.WriteString(w, "data: "+s+"\n\n")
			if f != nil {
				f.Flush()
			}
		}
		write(`{"choices":[{"delta":{"role":"assistant","content":""}}]}`)
		write(`{"choices":[{"delta":{"reasoning":"the user "}}]}`) // CoT, streamed first
		write(`{"choices":[{"delta":{"reasoning_content":"wants "}}]}`)
		write(`{"choices":[{"delta":{"thinking":"a greeting"}}]}`)
		write(`{"choices":[{"delta":{"content":"Hel"}}]}`)
		write(`{"choices":[{"delta":{"content":"lo"}}]}`)
		write(`{"choices":[{"delta":{}}],"usage":{"prompt_tokens":5,"completion_tokens":2}}`)
		write("[DONE]")
	}))
	defer srv.Close()

	c := NewChatProvider(srv.URL, "k", "m", 256, 4)
	ch, err := c.Stream(context.Background(), ports.ChatRequest{
		Messages: []ports.Message{{Role: ports.RoleUser, Content: "hi"}},
	})
	if err != nil {
		t.Fatal(err)
	}
	var content, reasoning string
	var done bool
	var usage *ports.Usage
	for chunk := range ch {
		if chunk.Done {
			done = true
			usage = chunk.Usage
			continue
		}
		// A chunk carries either reasoning or content — never both.
		if chunk.Reasoning != "" && chunk.Delta != "" {
			t.Fatalf("chunk carried both reasoning and content: %+v", chunk)
		}
		content += chunk.Delta
		reasoning += chunk.Reasoning
	}
	if content != "Hello" {
		t.Fatalf("expected answer content %q, got %q", "Hello", content)
	}
	if reasoning != "the user wants a greeting" {
		t.Fatalf("expected reasoning %q, got %q", "the user wants a greeting", reasoning)
	}
	if !done {
		t.Fatal("stream never signalled Done")
	}
	if usage == nil || usage.PromptTokens != 5 {
		t.Fatalf("expected usage prompt_tokens=5, got %+v", usage)
	}
}

func TestChatReportsUnexpectedEOFAsTerminalError(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		_, _ = io.WriteString(w, "data: {\"choices\":[{\"delta\":{\"content\":\"partial\"}}]}\n\n")
		// Deliberately close without [DONE] or finish_reason.
	}))
	defer srv.Close()

	c := NewChatProvider(srv.URL, "k", "m", 256, 4)
	ch, err := c.Stream(context.Background(), ports.ChatRequest{
		Messages: []ports.Message{{Role: ports.RoleUser, Content: "hi"}},
	})
	if err != nil {
		t.Fatal(err)
	}
	var content string
	var terminalErr error
	var done bool
	for chunk := range ch {
		content += chunk.Delta
		if chunk.Err != nil {
			terminalErr = chunk.Err
		}
		done = done || chunk.Done
	}
	if content != "partial" {
		t.Fatalf("expected partial content to be preserved, got %q", content)
	}
	if !errors.Is(terminalErr, ErrStreamInterrupted) {
		t.Fatalf("expected ErrStreamInterrupted, got %v", terminalErr)
	}
	if done {
		t.Fatal("interrupted stream must not emit Done")
	}
}

func TestChatReportsMalformedSSEData(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		_, _ = io.WriteString(w, "data: not-json\n\n")
	}))
	defer srv.Close()

	c := NewChatProvider(srv.URL, "k", "m", 256, 4)
	ch, err := c.Stream(context.Background(), ports.ChatRequest{
		Messages: []ports.Message{{Role: ports.RoleUser, Content: "hi"}},
	})
	if err != nil {
		t.Fatal(err)
	}
	var terminalErr error
	for chunk := range ch {
		terminalErr = chunk.Err
	}
	if !errors.Is(terminalErr, ErrMalformedStream) {
		t.Fatalf("expected ErrMalformedStream, got %v", terminalErr)
	}
}

// TestChatReasoningEffortPayload asserts the request body includes
// "reasoning_effort" only when ChatRequest.ReasoningEffort is non-empty.
func TestChatReasoningEffortPayload(t *testing.T) {
	run := func(effort string) map[string]any {
		var body map[string]any
		srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			b, _ := io.ReadAll(r.Body)
			_ = json.Unmarshal(b, &body)
			w.Header().Set("Content-Type", "text/event-stream")
			_, _ = io.WriteString(w, "data: [DONE]\n\n")
		}))
		defer srv.Close()
		c := NewChatProvider(srv.URL, "k", "m", 256, 4)
		ch, err := c.Stream(context.Background(), ports.ChatRequest{
			Messages:        []ports.Message{{Role: ports.RoleUser, Content: "hi"}},
			ReasoningEffort: effort,
		})
		if err != nil {
			t.Fatal(err)
		}
		for range ch { //nolint:revive // drain to release the pool slot
		}
		return body
	}

	if body := run("high"); body["reasoning_effort"] != "high" {
		t.Fatalf("expected reasoning_effort=high in payload, got %v", body["reasoning_effort"])
	}
	if body := run(""); body["reasoning_effort"] != nil {
		t.Fatalf("expected reasoning_effort omitted when empty, got %v", body["reasoning_effort"])
	}
}

// TestChatAssemblesStreamedToolCalls reproduces a real
// OpenAI-compatible (gpt-oss-120b) streaming tool_calls shape: id+name only on the first fragment for
// an index, argument JSON split across later fragments (reassembled by index),
// reasoning relayed before the call, then a terminal finish_reason=="tool_calls".
func TestChatAssemblesStreamedToolCalls(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		f, _ := w.(http.Flusher)
		write := func(s string) {
			_, _ = io.WriteString(w, "data: "+s+"\n\n")
			if f != nil {
				f.Flush()
			}
		}
		// CoT streams first, as in production.
		write(`{"choices":[{"delta":{"reasoning":"need to search jira"}}]}`)
		// First fragment: id + name, empty args.
		write(`{"choices":[{"delta":{"tool_calls":[{"id":"chatcmpl-tool-xyz","type":"function","index":0,"function":{"name":"jira_search","arguments":""}}]}}]}`)
		// Argument fragments by index (no id/name).
		write(`{"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\"jql\":"}}]}}]}`)
		write(`{"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"\"project=ABC\"}"}}]}}]}`)
		// Terminal: empty delta + finish_reason tool_calls.
		write(`{"choices":[{"delta":{},"finish_reason":"tool_calls"}]}`)
		write(`{"choices":[],"usage":{"prompt_tokens":10,"completion_tokens":3}}`)
		write("[DONE]")
	}))
	defer srv.Close()

	c := NewChatProvider(srv.URL, "k", "m", 256, 4)
	ch, err := c.Stream(context.Background(), ports.ChatRequest{
		Messages: []ports.Message{{Role: ports.RoleUser, Content: "open bugs?"}},
		Tools:    []ports.ToolSpec{{Name: "jira_search", Description: "Search", Parameters: json.RawMessage(`{"type":"object"}`)}},
	})
	if err != nil {
		t.Fatal(err)
	}
	var reasoning string
	var final ports.ChatChunk
	for chunk := range ch {
		reasoning += chunk.Reasoning
		if chunk.Done {
			final = chunk
		}
	}
	if reasoning != "need to search jira" {
		t.Fatalf("reasoning not relayed: %q", reasoning)
	}
	if final.FinishReason != "tool_calls" {
		t.Fatalf("expected finish_reason tool_calls, got %q", final.FinishReason)
	}
	if len(final.ToolCalls) != 1 {
		t.Fatalf("expected 1 assembled tool call, got %d (%+v)", len(final.ToolCalls), final.ToolCalls)
	}
	tc := final.ToolCalls[0]
	if tc.ID != "chatcmpl-tool-xyz" || tc.Name != "jira_search" {
		t.Fatalf("unexpected id/name: %+v", tc)
	}
	if tc.Arguments != `{"jql":"project=ABC"}` {
		t.Fatalf("arguments not reassembled by index: %q", tc.Arguments)
	}
	if final.Usage == nil || final.Usage.PromptTokens != 10 {
		t.Fatalf("expected usage on terminal chunk, got %+v", final.Usage)
	}
}

// TestChatToolsPayloadOnlyWhenPresent asserts the request body carries
// "tools"/"tool_choice" only when ChatRequest.Tools is non-empty — so a normal
// completion is byte-for-byte the legacy request.
func TestChatToolsPayloadOnlyWhenPresent(t *testing.T) {
	run := func(tools []ports.ToolSpec) map[string]any {
		var body map[string]any
		srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			b, _ := io.ReadAll(r.Body)
			_ = json.Unmarshal(b, &body)
			w.Header().Set("Content-Type", "text/event-stream")
			_, _ = io.WriteString(w, "data: [DONE]\n\n")
		}))
		defer srv.Close()
		c := NewChatProvider(srv.URL, "k", "m", 256, 4)
		ch, err := c.Stream(context.Background(), ports.ChatRequest{
			Messages: []ports.Message{{Role: ports.RoleUser, Content: "hi"}},
			Tools:    tools,
		})
		if err != nil {
			t.Fatal(err)
		}
		for range ch { //nolint:revive // drain to release the pool slot
		}
		return body
	}

	with := run([]ports.ToolSpec{{Name: "jira_search", Parameters: json.RawMessage(`{"type":"object"}`)}})
	if with["tools"] == nil || with["tool_choice"] != "auto" {
		t.Fatalf("expected tools + tool_choice=auto when tools present, got tools=%v choice=%v", with["tools"], with["tool_choice"])
	}
	without := run(nil)
	if without["tools"] != nil || without["tool_choice"] != nil {
		t.Fatalf("expected NO tools/tool_choice keys when no tools, got tools=%v choice=%v", without["tools"], without["tool_choice"])
	}
}

func TestChatShedsWhenPoolFull(t *testing.T) {
	c := NewChatProvider("http://unused", "k", "m", 256, 1)
	if !c.pool.tryAcquire() { // exhaust the only slot
		t.Fatal("expected to acquire the slot")
	}
	defer c.pool.release()

	_, err := c.Stream(context.Background(), ports.ChatRequest{
		Messages: []ports.Message{{Role: ports.RoleUser, Content: "hi"}},
	})
	if err != ErrUpstreamBusy {
		t.Fatalf("expected ErrUpstreamBusy when pool full, got %v", err)
	}
}

// The chat provider's response-header budget is configurable: a server that
// stalls before its first byte fails after it, and the default is 60s.
func TestChatProviderResponseHeaderTimeout(t *testing.T) {
	if got := NewChatProvider("http://unused", "k", "m", 256, 4).http.Transport.(*http.Transport).ResponseHeaderTimeout; got != 60*time.Second {
		t.Fatalf("default header timeout = %s, want 60s", got)
	}
	release := make(chan struct{})
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		<-release
	}))
	defer srv.Close()
	defer close(release)

	c := NewChatProvider(srv.URL, "k", "m", 256, 4).WithResponseHeaderTimeout(100 * time.Millisecond)
	if c.http.Transport != c.adminHTTP.Transport {
		t.Fatal("streaming and admin clients must share the LLM transport")
	}
	start := time.Now()
	_, err := c.Stream(context.Background(), ports.ChatRequest{Messages: []ports.Message{{Role: ports.RoleUser, Content: "hi"}}})
	if err == nil {
		t.Fatal("a stalled first byte must fail the stream")
	}
	if elapsed := time.Since(start); elapsed > 5*time.Second {
		t.Fatalf("header timeout not applied: %s", elapsed)
	}
}
