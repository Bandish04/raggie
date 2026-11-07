// SPDX-License-Identifier: Apache-2.0

package mcp

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

// tools/list pages from an untrusted MCP server: no panics, no nameless defs,
// and the read-only classification is consistent with the annotations.
func FuzzDecodeToolsList(f *testing.F) {
	for _, s := range []string{
		`{"tools":[{"name":"jira_search","inputSchema":{"type":"object"}}],"nextCursor":""}`,
		`{"tools":[{"name":"w","annotations":{"readOnlyHint":false,"destructiveHint":true}},{"name":""}]}`,
		`{"tools":[{"name":"get_x","annotations":{"readOnlyHint":true,"destructiveHint":true}}],"nextCursor":"p2"}`,
		`{"tools":null}`, `[]`, `{"tools":[{"annotations":"x"}]}`,
	} {
		f.Add([]byte(s))
	}
	f.Fuzz(func(t *testing.T, raw []byte) {
		defs, _, err := decodeToolsList(raw)
		if err != nil {
			return
		}
		for _, d := range defs {
			if d.Name == "" {
				t.Fatal("nameless tool def returned")
			}
			ro := d.IsReadOnly()
			if d.DestructiveHint != nil && *d.DestructiveHint && ro {
				t.Fatalf("destructive tool %q classified read-only", d.Name)
			}
			if d.ReadOnlyHint != nil && !*d.ReadOnlyHint && ro {
				t.Fatalf("tool %q with readOnlyHint=false classified read-only", d.Name)
			}
		}
	})
}

// Tool-name heuristic: a name containing any write verb is never read-only.
func FuzzToolDefIsReadOnly(f *testing.F) {
	for _, s := range []string{"jira_get_issue", "jira_create_issue", "confluence.search", "list-and-delete", "GET_x", ""} {
		f.Add(s)
	}
	f.Fuzz(func(t *testing.T, name string) {
		ro := ToolDef{Name: name}.IsReadOnly()
		if !ro {
			return
		}
		for _, tok := range strings.FieldsFunc(strings.ToLower(name), func(r rune) bool {
			return r == '_' || r == '-' || r == '.' || r == '/'
		}) {
			if writeVerbs[tok] {
				t.Fatalf("%q has write verb %q but was classified read-only", name, tok)
			}
		}
	})
}

// Arguments forwarded to MCP are always a single compact JSON object.
func FuzzNormalizeToolArguments(f *testing.F) {
	for _, s := range []string{`{"jql":"project=A"}`, ``, `[]`, `null`, `{"a":1}{"b":2}`, `{"n":1e999}`, `"x"`} {
		f.Add([]byte(s))
	}
	f.Fuzz(func(t *testing.T, raw []byte) {
		out, err := normalizeToolArguments(raw)
		if err != nil {
			return
		}
		// Numbers are preserved verbatim (UseNumber), so check JSON validity and
		// object shape rather than float64 representability.
		dec := json.NewDecoder(bytes.NewReader(out))
		dec.UseNumber()
		var obj map[string]any
		if !json.Valid(out) || dec.Decode(&obj) != nil || obj == nil {
			t.Fatalf("normalized arguments are not a JSON object: %s", out)
		}
	})
}

// JSON-RPC responses over SSE / JSON from an untrusted server: no panics, and
// a returned response always carries the requested id (or is an id-less error).
func FuzzReadRPCResponse(f *testing.F) {
	for _, s := range []string{
		"event: message\ndata: {\"jsonrpc\":\"2.0\",\"id\":7,\"result\":{}}\n\n",
		"data: {\"id\":\"7\",\"result\":1}\n",
		"data: [{\"id\":1},{\"id\":7,\"result\":2}]\n\n",
		"data: {\"error\":{\"code\":-32700,\"message\":\"parse\"}}\n\n",
		": keepalive\n\ndata: [DONE]\n\n",
	} {
		f.Add([]byte(s), true)
		f.Add([]byte(strings.TrimPrefix(strings.SplitN(s, "\n", 2)[0], "data: ")), false)
	}
	f.Fuzz(func(t *testing.T, body []byte, sse bool) {
		if len(body) > 256<<10 {
			return
		}
		ct := "application/json"
		if sse {
			ct = "text/event-stream"
		}
		resp := &http.Response{Header: http.Header{"Content-Type": []string{ct}}, Body: io.NopCloser(bytes.NewReader(body))}
		r, err := readRPCResponse(resp, 7)
		if err != nil || r == nil {
			return
		}
		if len(r.ID) > 0 && !idMatches(r.ID, 7) {
			t.Fatalf("returned response with id %s, want 7", r.ID)
		}
		if len(r.ID) == 0 && r.Error == nil {
			t.Fatal("returned an id-less non-error response")
		}
	})
}

// A hostile server that repeats nextCursor forever must not trap tools/list
// in an endless loop.
func TestFetchToolsStopsOnCursorLoop(t *testing.T) {
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
			writeResult(w, *env.ID, `{"tools":[{"name":"t"}],"nextCursor":"again"}`)
		}
	}))
	defer srv.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	done := make(chan error, 1)
	go func() {
		_, err := New(srv.URL, 4).ListTools(ctx)
		done <- err
	}()
	select {
	case err := <-done:
		if err == nil {
			t.Fatal("expected an error for a repeating cursor")
		}
	case <-ctx.Done():
		t.Fatal("tools/list never terminated on a repeating cursor")
	}
}
