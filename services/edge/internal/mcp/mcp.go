// SPDX-License-Identifier: Apache-2.0

// Package mcp is a minimal, pure-Go client for the Model Context Protocol over
// the "streamable-HTTP" transport (a single POST endpoint speaking JSON-RPC 2.0,
// answering with either application/json or an SSE text/event-stream body).
//
// It is deliberately hand-rolled (no third-party MCP SDK) so the edge stays
// pure-Go on its distroless runtime and has zero new dependencies. Phase 1 only
// needs three verbs against a self-hosted mcp-atlassian container:
//
//	initialize -> notifications/initialized -> tools/list -> tools/call
//
// The client (re)initializes lazily on first use and is safe for concurrent
// reuse. It is fail-soft by design: callers (the chat handler) log any error and
// proceed WITHOUT tools, so MCP problems never break the chat.
package mcp

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/alicangunduz/raggie/services/edge/internal/outboundhttp"
)

// ToolDef is one tool advertised by the MCP server: its name, human description,
// and the raw JSON Schema for its arguments (passed through to the LLM verbatim).
type ToolDef struct {
	Name        string
	Description string
	InputSchema json.RawMessage
	// ReadOnlyHint / DestructiveHint mirror the MCP tool annotations
	// (annotations.readOnlyHint / destructiveHint); nil when the server omits them.
	ReadOnlyHint    *bool
	DestructiveHint *bool
}

// readVerbs / writeVerbs / chainTokens drive the name heuristic used when a
// server does not annotate its tools. Anything that can write wins, and an
// unknown verb is NOT read-only. "query" is deliberately not a read verb: SQL
// and GraphQL queries can mutate (sql_query, run_query).
var (
	readVerbs = map[string]bool{
		"get": true, "search": true, "list": true, "read": true, "fetch": true,
		"find": true, "describe": true, "lookup": true,
		"show": true, "view": true, "count": true,
	}
	writeVerbs = map[string]bool{
		"create": true, "update": true, "delete": true, "remove": true, "add": true,
		"set": true, "transition": true, "edit": true, "move": true, "link": true,
		"unlink": true, "assign": true, "upload": true, "download": true,
		"post": true, "put": true, "patch": true, "send": true, "write": true,
		"archive": true, "close": true, "merge": true, "import": true,
		"execute": true, "run": true, "approve": true, "reject": true,
		"insert": true, "replace": true, "drop": true, "purge": true, "terminate": true,
		"cancel": true, "comment": true, "mark": true, "publish": true, "submit": true,
		"revoke": true, "grant": true, "reset": true, "save": true, "upsert": true,
		"modify": true,
		// Arbitrary execution, whatever verb precedes it.
		"exec": true, "eval": true, "sql": true, "shell": true, "command": true, "script": true,
	}
	// chainTokens join a second action onto a read verb (search_and_replace,
	// get_or_insert, list_then_purge): the name no longer describes one read.
	chainTokens = map[string]bool{"and": true, "or": true, "then": true}
)

// IsReadOnly reports whether the tool is provably side-effect free. An
// explicit destructiveHint=true never is; an explicit readOnlyHint decides
// otherwise. Without annotations the name must contain a read verb (e.g.
// jira_get_issue, after any service prefix) and no write verb, execution
// marker or chaining word anywhere.
func (d ToolDef) IsReadOnly() bool {
	if d.DestructiveHint != nil && *d.DestructiveHint {
		return false
	}
	if d.ReadOnlyHint != nil {
		return *d.ReadOnlyHint
	}
	sawRead := false
	for _, tok := range strings.FieldsFunc(strings.ToLower(d.Name), func(r rune) bool {
		return r == '_' || r == '-' || r == '.' || r == '/'
	}) {
		if writeVerbs[tok] || chainTokens[tok] {
			return false
		}
		if readVerbs[tok] {
			sawRead = true
		}
	}
	return sawRead
}

// ToolProvider is the small surface the chat handler depends on. A nil provider
// (feature disabled) means tools are never offered.
type ToolProvider interface {
	// ListTools returns the server's advertised tools (initializing lazily).
	ListTools(ctx context.Context) ([]ToolDef, error)
	// CallTool invokes one tool and returns its result content flattened to text
	// (text content blocks concatenated). isError mirrors the MCP result's
	// isError flag (a tool-level failure, distinct from a transport err).
	CallTool(ctx context.Context, name string, argsJSON json.RawMessage) (text string, isError bool, err error)
}

// VersionedProvider is an optional extension of ToolProvider that surfaces the
// MCP protocol version negotiated with the server plus a health probe and a
// tools-cache refresh. It is narrow on purpose so existing stubs/tests that only
// implement ToolProvider do not need to change (the admin endpoint type-asserts
// for it and degrades gracefully when it is absent).
type VersionedProvider interface {
	ToolProvider
	// ProtocolVersion returns the server-negotiated MCP protocol version (or "" if
	// the handshake has not happened yet).
	ProtocolVersion() string
	// HealthCheck performs a lightweight probe (a handshake + tools/list) and
	// reports status, the negotiated version, and the round-trip latency. err is
	// non-nil only on a transport/handshake failure.
	HealthCheck(ctx context.Context) (status HealthStatus, err error)
	// RefreshTools invalidates the tools/list TTL cache and re-fetches.
	RefreshTools(ctx context.Context) ([]ToolDef, error)
}

// HealthStatus is the result of a HealthCheck probe.
type HealthStatus struct {
	Version   string        // negotiated MCP protocol version
	ToolCount int           // number of advertised tools
	Latency   time.Duration // probe round-trip
}

const (
	protocolVersion    = "2025-03-26" // MCP protocol version we ADVERTISE on initialize
	defaultListTimeo   = 15 * time.Second
	defaultCallTimeo   = 30 * time.Second
	initializeTimeout  = 15 * time.Second
	toolsCacheTTL      = 60 * time.Second // tools/list result cache window
	maxToolResultRunes = 32000
)

// Client is a streamable-HTTP MCP client for a single server URL.
type Client struct {
	url       string
	http      *http.Client
	maxIters  int // advisory: surfaced for the handler's loop cap (see MaxIterations)
	idCounter atomic.Int64
	logger    *slog.Logger

	mu          sync.Mutex // guards init handshake + sessionID + negotiated version + tools cache
	inited      bool
	sessionID   string
	negotiatedV string // server-negotiated protocolVersion (captured on initialize)

	// tools/list TTL cache (~60s): a successful list is cached so the hot path
	// (every chat turn that offers tools) does not re-hit the server each time.
	cachedTools []ToolDef
	cachedAt    time.Time

	listTimeo time.Duration
	callTimeo time.Duration
	initTimeo time.Duration

	// Lightweight counters (atomic) surfaced via Counters() for /metrics.
	callTotal  atomic.Int64
	callErrors atomic.Int64
}

// New builds a client for the given streamable-HTTP endpoint (e.g.
// "http://mcp-atlassian:9000/mcp"). maxIterations is carried for the caller's
// agentic-loop cap; it does not affect the transport.
func New(url string, maxIterations int) *Client {
	return &Client{
		url:       url,
		http:      outboundhttp.NewClient(0), // per-request deadlines via context
		maxIters:  maxIterations,
		logger:    slog.Default(),
		listTimeo: defaultListTimeo,
		callTimeo: defaultCallTimeo,
		initTimeo: initializeTimeout,
	}
}

// WithLogger sets a structured logger for per-call diagnostics (defaults to
// slog.Default()). Returns the client for chaining.
func (c *Client) WithLogger(l *slog.Logger) *Client {
	if l != nil {
		c.logger = l
	}
	return c
}

// MaxIterations returns the configured agentic-loop cap (advisory; the handler
// owns the loop).
func (c *Client) MaxIterations() int { return c.maxIters }

// ProtocolVersion returns the server-negotiated MCP protocol version, or "" if
// the handshake has not yet succeeded.
func (c *Client) ProtocolVersion() string {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.negotiatedV
}

// Counters returns the cumulative CallTool totals (for /metrics).
func (c *Client) Counters() (total, errors int64) {
	return c.callTotal.Load(), c.callErrors.Load()
}

// ── JSON-RPC envelopes ────────────────────────────────────────────────────────

type rpcRequest struct {
	JSONRPC string `json:"jsonrpc"`
	ID      int64  `json:"id"`
	Method  string `json:"method"`
	Params  any    `json:"params,omitempty"`
}

type rpcNotification struct {
	JSONRPC string `json:"jsonrpc"`
	Method  string `json:"method"`
	Params  any    `json:"params,omitempty"`
}

type rpcResponse struct {
	JSONRPC string          `json:"jsonrpc"`
	ID      json.RawMessage `json:"id"`
	Result  json.RawMessage `json:"result"`
	Error   *rpcError       `json:"error"`
}

type rpcError struct {
	Code    int    `json:"code"`
	Message string `json:"message"`
}

func (e *rpcError) Error() string { return fmt.Sprintf("mcp rpc error %d: %s", e.Code, e.Message) }

// ── Public API ────────────────────────────────────────────────────────────────

// ListTools returns the advertised tools, initializing the session if needed.
// A successful result is cached for toolsCacheTTL so the chat hot path does not
// re-fetch on every turn; RefreshTools forces a re-fetch.
func (c *Client) ListTools(ctx context.Context) ([]ToolDef, error) {
	if cached, ok := c.cachedToolsFresh(); ok {
		return cached, nil
	}
	return c.fetchTools(ctx)
}

// RefreshTools invalidates the TTL cache and re-fetches the tools/list.
func (c *Client) RefreshTools(ctx context.Context) ([]ToolDef, error) {
	c.mu.Lock()
	c.cachedTools = nil
	c.cachedAt = time.Time{}
	c.mu.Unlock()
	return c.fetchTools(ctx)
}

// cachedToolsFresh returns the cached tools if the TTL window has not elapsed.
func (c *Client) cachedToolsFresh() ([]ToolDef, bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.cachedTools != nil && time.Since(c.cachedAt) < toolsCacheTTL {
		return c.cachedTools, true
	}
	return nil, false
}

// fetchTools performs the live tools/list (re-handshaking once on a stale
// session) and updates the TTL cache.
func (c *Client) fetchTools(ctx context.Context) ([]ToolDef, error) {
	if err := c.ensureInit(ctx); err != nil {
		return nil, err
	}
	defs := []ToolDef{}
	cursor := ""
	seen := map[string]bool{}
	for page := 0; ; page++ {
		// An untrusted server must not be able to page forever.
		if page >= maxToolListPages {
			return nil, fmt.Errorf("mcp tools/list: more than %d pages", maxToolListPages)
		}
		params := map[string]any{}
		if cursor != "" {
			params["cursor"] = cursor
		}
		raw, err := c.callRetry(ctx, c.listTimeo, "tools/list", params)
		if err != nil {
			return nil, err
		}
		page, next, err := decodeToolsList(raw)
		if err != nil {
			return nil, err
		}
		defs = append(defs, page...)
		if next == "" {
			break
		}
		if seen[next] {
			return nil, fmt.Errorf("mcp tools/list: repeated cursor")
		}
		seen[next] = true
		cursor = next
	}
	c.mu.Lock()
	c.cachedTools = defs
	c.cachedAt = time.Now()
	c.mu.Unlock()
	return defs, nil
}

// maxToolListPages bounds tools/list pagination from an untrusted server.
const maxToolListPages = 100

// decodeToolsList parses one tools/list result page into tool defs (nameless
// entries are dropped) and returns the next-page cursor.
func decodeToolsList(raw json.RawMessage) ([]ToolDef, string, error) {
	var out struct {
		Tools []struct {
			Name        string          `json:"name"`
			Description string          `json:"description"`
			InputSchema json.RawMessage `json:"inputSchema"`
			Annotations struct {
				ReadOnlyHint    *bool `json:"readOnlyHint"`
				DestructiveHint *bool `json:"destructiveHint"`
			} `json:"annotations"`
		} `json:"tools"`
		NextCursor string `json:"nextCursor"`
	}
	if err := json.Unmarshal(raw, &out); err != nil {
		return nil, "", fmt.Errorf("mcp tools/list decode: %w", err)
	}
	defs := make([]ToolDef, 0, len(out.Tools))
	for _, t := range out.Tools {
		if t.Name == "" {
			continue
		}
		defs = append(defs, ToolDef{
			Name:            t.Name,
			Description:     t.Description,
			InputSchema:     t.InputSchema,
			ReadOnlyHint:    t.Annotations.ReadOnlyHint,
			DestructiveHint: t.Annotations.DestructiveHint,
		})
	}
	return defs, out.NextCursor, nil
}

// HealthCheck probes the server (handshake + tools/list, which doubles as a
// health + version check) and reports status, the negotiated version, and the
// round-trip latency. The tools/list goes through the TTL cache like the hot
// path, so a healthy server is cheap to re-probe.
func (c *Client) HealthCheck(ctx context.Context) (HealthStatus, error) {
	start := time.Now()
	defs, err := c.ListTools(ctx)
	latency := time.Since(start)
	if err != nil {
		return HealthStatus{Latency: latency}, err
	}
	return HealthStatus{
		Version:   c.ProtocolVersion(),
		ToolCount: len(defs),
		Latency:   latency,
	}, nil
}

// CallTool invokes one tool and flattens its text content blocks. It logs a
// structured per-call line + bumps counters, and re-handshakes once on a stale
// session (401 / session-expired RPC error).
func (c *Client) CallTool(ctx context.Context, name string, argsJSON json.RawMessage) (string, bool, error) {
	start := time.Now()
	c.callTotal.Add(1)
	if err := c.ensureInit(ctx); err != nil {
		c.callErrors.Add(1)
		c.logCall(name, start, false, err)
		return "", false, err
	}

	args, err := normalizeToolArguments(argsJSON)
	if err != nil {
		c.callErrors.Add(1)
		c.logCall(name, start, false, err)
		return "", false, err
	}
	params := map[string]any{"name": name, "arguments": args}
	raw, err := c.callRetry(ctx, c.callTimeo, "tools/call", params)
	if err != nil {
		c.callErrors.Add(1)
		c.logCall(name, start, false, err)
		return "", false, err
	}
	var res struct {
		IsError           bool            `json:"isError"`
		StructuredContent json.RawMessage `json:"structuredContent"`
		Content           []struct {
			Type string `json:"type"`
			Text string `json:"text"`
		} `json:"content"`
	}
	if err := json.Unmarshal(raw, &res); err != nil {
		c.callErrors.Add(1)
		c.logCall(name, start, false, err)
		return "", false, fmt.Errorf("mcp tools/call decode: %w", err)
	}
	var b strings.Builder
	if len(bytes.TrimSpace(res.StructuredContent)) > 0 {
		var compact bytes.Buffer
		if err := json.Compact(&compact, res.StructuredContent); err == nil && compact.Len() > 0 {
			b.WriteString("structuredContent: ")
			b.Write(compact.Bytes())
		}
	}
	for _, blk := range res.Content {
		// Phase 1 is READ-only and Jira tools return text blocks; non-text blocks
		// (e.g. images) are skipped — their text is empty anyway.
		if blk.Text == "" {
			continue
		}
		if b.Len() > 0 {
			b.WriteString("\n")
		}
		b.WriteString(blk.Text)
	}
	if res.IsError {
		c.callErrors.Add(1)
	}
	c.logCall(name, start, !res.IsError, nil)
	return truncateToolResult(b.String()), res.IsError, nil
}

func truncateToolResult(s string) string {
	r := []rune(s)
	if len(r) <= maxToolResultRunes {
		return s
	}
	return string(r[:maxToolResultRunes]) + "\n\n[Tool result truncated by Raggie before model ingestion.]"
}

func normalizeToolArguments(argsJSON json.RawMessage) (json.RawMessage, error) {
	trimmed := bytes.TrimSpace(argsJSON)
	if len(trimmed) == 0 {
		trimmed = []byte(`{}`)
	}
	dec := json.NewDecoder(bytes.NewReader(trimmed))
	dec.UseNumber()
	var obj map[string]any
	if err := dec.Decode(&obj); err != nil {
		return nil, fmt.Errorf("mcp tools/call arguments must be a JSON object: %w", err)
	}
	if obj == nil {
		return nil, fmt.Errorf("mcp tools/call arguments must be a JSON object")
	}
	var extra any
	if err := dec.Decode(&extra); err != io.EOF {
		if err == nil {
			return nil, fmt.Errorf("mcp tools/call arguments must contain a single JSON object")
		}
		return nil, err
	}
	compact, err := json.Marshal(obj)
	if err != nil {
		return nil, err
	}
	return json.RawMessage(compact), nil
}

// logCall emits a structured per-CallTool line (tool name, latency, outcome).
func (c *Client) logCall(name string, start time.Time, ok bool, err error) {
	if c.logger == nil {
		return
	}
	attrs := []any{"tool", name, "latency_ms", time.Since(start).Milliseconds(), "ok", ok}
	if err != nil {
		c.logger.Warn("mcp tools/call", append(attrs, "err", err)...)
		return
	}
	c.logger.Info("mcp tools/call", attrs...)
}

// ── Handshake ─────────────────────────────────────────────────────────────────

// ensureInit performs the initialize + notifications/initialized handshake once.
// Concurrent callers block on the mutex; the first one does the handshake. A
// failure leaves inited=false so a later call retries (fail-soft).
func (c *Client) ensureInit(ctx context.Context) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.inited {
		return nil
	}
	ictx, cancel := context.WithTimeout(ctx, c.initTimeo)
	defer cancel()

	initParams := map[string]any{
		"protocolVersion": protocolVersion,
		"capabilities":    map[string]any{},
		"clientInfo":      map[string]any{"name": "raggie-edge", "version": "1"},
	}
	raw, err := c.call(ictx, "initialize", initParams)
	if err != nil {
		return fmt.Errorf("mcp initialize: %w", err)
	}
	// Capture the server-NEGOTIATED protocol version (it may differ from the one
	// we advertised). Previously parsed-and-discarded; now surfaced for health.
	var initRes struct {
		ProtocolVersion string `json:"protocolVersion"`
	}
	if uerr := json.Unmarshal(raw, &initRes); uerr == nil && initRes.ProtocolVersion != "" {
		c.negotiatedV = initRes.ProtocolVersion
	} else {
		c.negotiatedV = protocolVersion // fall back to the advertised version
	}
	// Per spec the client MUST send the initialized notification before normal
	// operations. A notification has no response.
	if err := c.notify(ictx, "notifications/initialized", map[string]any{}); err != nil {
		return fmt.Errorf("mcp initialized notify: %w", err)
	}
	c.inited = true
	return nil
}

// callRetry runs a JSON-RPC call with a per-call timeout; on a session-expired
// error (401 / "session" RPC error) it resets the handshake state and retries
// ONCE — so a server restart or expired session self-heals on the next call
// instead of getting stuck. Other errors propagate unchanged.
func (c *Client) callRetry(ctx context.Context, timeo time.Duration, method string, params any) (json.RawMessage, error) {
	cctx, cancel := context.WithTimeout(ctx, timeo)
	defer cancel()
	raw, err := c.call(cctx, method, params)
	if err == nil || !isSessionExpired(err) {
		return raw, err
	}
	// Stale session: drop it, re-handshake, and try once more.
	c.resetSession()
	if ierr := c.ensureInit(ctx); ierr != nil {
		return nil, ierr
	}
	rctx, rcancel := context.WithTimeout(ctx, timeo)
	defer rcancel()
	return c.call(rctx, method, params)
}

// resetSession clears the handshake + session id so the next call re-initializes.
func (c *Client) resetSession() {
	c.mu.Lock()
	c.inited = false
	c.sessionID = ""
	c.mu.Unlock()
}

// isSessionExpired reports whether an error looks like a stale/expired MCP
// session (an HTTP 401/403 from post, or an RPC error mentioning the session)
// that a re-handshake can recover from.
func isSessionExpired(err error) bool {
	if err == nil {
		return false
	}
	msg := strings.ToLower(err.Error())
	return strings.Contains(msg, "status 401") ||
		strings.Contains(msg, "status 403") ||
		strings.Contains(msg, "session") ||
		strings.Contains(msg, "not initialized")
}

// ── Transport ─────────────────────────────────────────────────────────────────

// call sends one JSON-RPC request and returns its result payload. It handles a
// response delivered either as a single JSON body or inside an SSE stream.
func (c *Client) call(ctx context.Context, method string, params any) (json.RawMessage, error) {
	id := c.idCounter.Add(1)
	reqBody, err := json.Marshal(rpcRequest{JSONRPC: "2.0", ID: id, Method: method, Params: params})
	if err != nil {
		return nil, err
	}

	httpResp, err := c.post(ctx, reqBody)
	if err != nil {
		return nil, err
	}
	defer httpResp.Body.Close()

	// Capture a freshly-issued session id (the server assigns it on initialize).
	if sid := httpResp.Header.Get("Mcp-Session-Id"); sid != "" {
		c.sessionID = sid
	}
	if httpResp.StatusCode < 200 || httpResp.StatusCode >= 300 {
		body, _ := io.ReadAll(io.LimitReader(httpResp.Body, 2048))
		return nil, fmt.Errorf("mcp %s: status %d: %s", method, httpResp.StatusCode, strings.TrimSpace(string(body)))
	}

	resp, err := readRPCResponse(httpResp, id)
	if err != nil {
		return nil, fmt.Errorf("mcp %s: %w", method, err)
	}
	if resp.Error != nil {
		return nil, resp.Error
	}
	return resp.Result, nil
}

// notify sends a JSON-RPC notification (no id, no response body expected).
func (c *Client) notify(ctx context.Context, method string, params any) error {
	body, _ := json.Marshal(rpcNotification{JSONRPC: "2.0", Method: method, Params: params})
	resp, err := c.post(ctx, body)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if sid := resp.Header.Get("Mcp-Session-Id"); sid != "" {
		c.sessionID = sid
	}
	// 200/202 (or any 2xx) is success; drain whatever the server returned.
	_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 1<<16))
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("mcp notify %s: status %d", method, resp.StatusCode)
	}
	return nil
}

// post issues the raw HTTP POST with the MCP headers (Accept both content types,
// carry the session id once known).
func (c *Client) post(ctx context.Context, body []byte) (*http.Response, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.url, bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "application/json, text/event-stream")
	if c.sessionID != "" {
		req.Header.Set("Mcp-Session-Id", c.sessionID)
	}
	return c.http.Do(req)
}

// readRPCResponse reads the JSON-RPC response from either a plain JSON body or an
// SSE stream. For SSE it scans `data:` lines (concatenating multi-line data) and
// returns the first message whose id matches the request id (a string- or
// number-encoded id both compare by their raw bytes after normalisation).
func readRPCResponse(resp *http.Response, wantID int64) (*rpcResponse, error) {
	ct := resp.Header.Get("Content-Type")
	if strings.Contains(ct, "text/event-stream") {
		return readSSEResponse(resp.Body, wantID)
	}
	// Plain JSON body (may, in theory, be a batch array — handle the common
	// single-object case and fall back to scanning an array).
	raw, err := io.ReadAll(io.LimitReader(resp.Body, 8<<20))
	if err != nil {
		return nil, err
	}
	return parseRPCPayload(raw, wantID)
}

// readSSEResponse consumes an SSE body until it finds the JSON-RPC response whose
// id matches wantID. Server-pushed unrelated messages (other ids, notifications
// without an id) are skipped.
func readSSEResponse(body io.Reader, wantID int64) (*rpcResponse, error) {
	sc := bufio.NewScanner(body)
	sc.Buffer(make([]byte, 64*1024), 4<<20)
	var dataLines []string
	flush := func() (*rpcResponse, bool, error) {
		if len(dataLines) == 0 {
			return nil, false, nil
		}
		payload := strings.Join(dataLines, "\n")
		dataLines = dataLines[:0]
		if strings.TrimSpace(payload) == "" || payload == "[DONE]" {
			return nil, false, nil
		}
		r, err := parseRPCPayload([]byte(payload), wantID)
		if err != nil {
			// Not our message (id mismatch / notification) — keep scanning.
			return nil, false, nil
		}
		return r, true, nil
	}
	for sc.Scan() {
		line := sc.Text()
		switch {
		case line == "": // event terminator — try to parse what we buffered
			if r, ok, _ := flush(); ok {
				return r, nil
			}
		case strings.HasPrefix(line, "data:"):
			dataLines = append(dataLines, strings.TrimSpace(line[len("data:"):]))
		default:
			// ignore event:, id:, retry:, comments (":")
		}
	}
	if err := sc.Err(); err != nil {
		return nil, err
	}
	// Stream ended; try any trailing buffered event.
	if r, ok, _ := flush(); ok {
		return r, nil
	}
	return nil, fmt.Errorf("no matching JSON-RPC response (id %d) in SSE stream", wantID)
}

// parseRPCPayload decodes a single JSON-RPC response object, or a batch array,
// and returns the entry whose id matches wantID. An id mismatch is an error so
// the SSE scanner keeps looking.
func parseRPCPayload(raw []byte, wantID int64) (*rpcResponse, error) {
	trimmed := bytes.TrimSpace(raw)
	if len(trimmed) == 0 {
		return nil, fmt.Errorf("empty payload")
	}
	if trimmed[0] == '[' {
		var batch []rpcResponse
		if err := json.Unmarshal(trimmed, &batch); err != nil {
			return nil, err
		}
		for i := range batch {
			if idMatches(batch[i].ID, wantID) {
				return &batch[i], nil
			}
		}
		return nil, fmt.Errorf("id %d not in batch", wantID)
	}
	var r rpcResponse
	if err := json.Unmarshal(trimmed, &r); err != nil {
		return nil, err
	}
	// A response with no id but an error is still meaningful (e.g. parse error).
	if len(r.ID) == 0 {
		if r.Error != nil {
			return &r, nil
		}
		return nil, fmt.Errorf("response without id")
	}
	if !idMatches(r.ID, wantID) {
		return nil, fmt.Errorf("id mismatch")
	}
	return &r, nil
}

// idMatches compares a JSON-RPC id (number or string-encoded number) to wantID.
func idMatches(rawID json.RawMessage, wantID int64) bool {
	s := strings.TrimSpace(string(rawID))
	s = strings.Trim(s, `"`)
	return s == fmt.Sprintf("%d", wantID)
}

var (
	_ ToolProvider      = (*Client)(nil)
	_ VersionedProvider = (*Client)(nil)
)
