// SPDX-License-Identifier: Apache-2.0

// Package agent is the transport-agnostic agentic core: a flat Registry of
// callable Tools plus a Run loop that generalises the tool-calling loop the chat
// handler used to inline. It streams a turn, relays reasoning/content via
// injected emit closures, invokes any requested tools, feeds the results back,
// and loops up to a cap.
//
// CRITICAL backward-compat invariant: when the registry has NO enabled tools,
// Run makes exactly ONE Stream call and relays content/reasoning exactly like
// the legacy non-tool path — byte-for-byte identical SSE. The web / deep / MCP
// tools become entries in this registry; an empty registry is pure documents
// RAG.
package agent

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"strings"
	"time"

	"github.com/alicangunduz/raggie/services/edge/internal/ports"
)

// Tool is one callable capability advertised to the model. Spec is the
// OpenAI-style function spec (name/description/JSON-Schema). Invoke runs the
// tool with the model-supplied raw JSON arguments and returns the result text
// (fed back to the model), an isErr flag (a tool-level failure, distinct from a
// transport err), and a Go error for an invocation failure.
type Tool struct {
	Spec   ports.ToolSpec
	Kind   string
	Invoke func(ctx context.Context, argsJSON json.RawMessage) (text string, isErr bool, err error)
}

// Registry is the per-turn flat set of enabled tools, in a stable order. It is
// built by the caller from the enabled features (web/deep/MCP), already filtered
// by per-feature gates and the optional skill allow-list.
type Registry struct {
	tools  []Tool
	byName map[string]Tool
}

// NewRegistry builds a registry from an ordered tool slice (nameless tools are
// dropped; a later tool with a duplicate name wins, matching map semantics).
func NewRegistry(tools ...Tool) *Registry {
	r := &Registry{byName: make(map[string]Tool, len(tools))}
	for _, t := range tools {
		if t.Spec.Name == "" || t.Invoke == nil {
			continue
		}
		if _, dup := r.byName[t.Spec.Name]; !dup {
			r.tools = append(r.tools, t)
		}
		r.byName[t.Spec.Name] = t
	}
	return r
}

// Add appends a tool (skipping nameless / nil-invoke ones). Returns the registry
// for chaining.
func (r *Registry) Add(t Tool) *Registry {
	if t.Spec.Name == "" || t.Invoke == nil {
		return r
	}
	if _, dup := r.byName[t.Spec.Name]; !dup {
		r.tools = append(r.tools, t)
	}
	r.byName[t.Spec.Name] = t
	return r
}

// Empty reports whether the registry advertises no tools (⇒ Run does a single
// legacy Stream call).
func (r *Registry) Empty() bool { return r == nil || len(r.tools) == 0 }

// Specs returns the advertised tool specs in registry order (for the Stream
// request's Tools field).
func (r *Registry) Specs() []ports.ToolSpec {
	if r == nil {
		return nil
	}
	specs := make([]ports.ToolSpec, 0, len(r.tools))
	for _, t := range r.tools {
		specs = append(specs, t.Spec)
	}
	return specs
}

// lookup returns the tool registered under name, if any.
func (r *Registry) lookup(name string) (Tool, bool) {
	if r == nil {
		return Tool{}, false
	}
	t, ok := r.byName[name]
	return t, ok
}

// Emit writes one SSE-style event. An empty event name produces a bare data line
// (the answer-delta channel); a non-empty name produces an `event: <name>`
// block. data is the already-marshalled JSON payload. The handler injects this
// to keep the SSE wire format and ordering exactly as before.
type Emit func(event string, data []byte)

// RunParams configures one Run. Chat streams the completion; Messages is the
// seeded message list (system grounding + history + user turn). Temperature /
// Model / ReasoningEffort mirror the request. ToolChoice ("auto"|"required") is
// forwarded to the provider when the registry is non-empty. MaxIterations caps
// the loop. IterLimitNote is the localized note appended when the cap is hit
// with no answer yet.
type RunParams struct {
	Chat            ports.ChatProvider
	Messages        []ports.Message
	Temperature     float32
	Model           string
	ReasoningEffort string
	ToolChoice      string
	MaxIterations   int
	IterLimitNote   string
	// IterLimitThinkingNote is shown on the reasoning channel when the cap is
	// hit (localized by the caller; English default).
	IterLimitThinkingNote string
	// StreamReasoning relays the model's raw chain-of-thought on the "thinking"
	// channel. Off by default (STREAM_REASONING): reasoning is dropped.
	StreamReasoning bool
}

// Result reports the outcome of Run to the handler so it can persist the answer
// and emit the terminal markers exactly as before.
type Result struct {
	Answer         string          // the FINAL answer text (intermediate turns excluded)
	Usage          *ports.Usage    // token accounting from the terminal turn, if reported
	Completed      bool            // the stream finished cleanly (terminal Done seen)
	ToolExecutions []ToolExecution // audit-safe summary of tool invocations
	// Err carries an upstream error (e.g. ErrUpstreamBusy) the caller may inspect
	// (e.g. to choose a "busy" vs generic stream error). The loop has already
	// stopped; the caller is expected to surface it as an SSE error.
	Err error
}

// ToolExecution is an audit-safe per-tool summary. It deliberately omits raw
// arguments and full results; the hash is enough to correlate repeated calls
// without storing potentially sensitive Jira/web payloads.
type ToolExecution struct {
	ID          string
	Name        string
	Kind        string
	OK          bool
	LatencyMS   int64
	Error       string
	ArgsSHA256  string
	ResultChars int
}

// Run executes the agentic turn. It Streams the seeded messages; on each turn it
// relays reasoning on the "thinking" channel and answer content on the bare-data
// channel via emit. If a turn finishes by requesting tools, each call is invoked
// (emitting tool_call/tool_result), its result appended as a tool message, and
// the loop continues; a turn that finishes with plain content (no tool calls) is
// the FINAL answer. With an EMPTY registry the very first Stream carries no tools
// and the first non-tool turn ends the loop — exactly one Stream call, identical
// to the legacy single-stream path.
//
// emit writes SSE events (see Emit). On an upstream error Run stops and returns
// Result.Err set (it does NOT emit — the caller maps it to the right SSE error
// because only the caller knows whether headers are already sent). A client
// abort (ctx cancelled) stops quietly, persisting whatever partial accumulated.
func Run(ctx context.Context, p RunParams, emit Emit) Result {
	return runWith(ctx, nil, p, emit)
}

// RunWithTools is Run with a tool registry. It is the general entrypoint; Run is
// the convenience wrapper for the no-tools case.
func RunWithTools(ctx context.Context, reg *Registry, p RunParams, emit Emit) Result {
	return runWith(ctx, reg, p, emit)
}

func runWith(ctx context.Context, reg *Registry, p RunParams, emit Emit) Result {
	var res Result
	msgs := p.Messages
	maxIters := p.MaxIterations
	if maxIters < 1 {
		maxIters = 1
	}
	// With no tools, a single iteration mirrors the legacy single-stream path.
	if reg.Empty() {
		maxIters = 1
	}

	for iter := 0; iter < maxIters; iter++ {
		specs := reg.Specs()
		req := ports.ChatRequest{
			Messages:        msgs,
			Temperature:     p.Temperature,
			Model:           p.Model,
			ReasoningEffort: p.ReasoningEffort,
		}
		if len(specs) > 0 {
			req.Tools = specs
			req.ToolChoice = p.ToolChoice
		}
		ts, serr := p.Chat.Stream(ctx, req)
		if serr != nil {
			res.Err = serr
			return res
		}

		// Consume this turn. Relay reasoning/content live; the terminal chunk may
		// carry reassembled tool calls (finish_reason=="tool_calls").
		var turnText strings.Builder
		var toolCalls []ports.ToolCall
		turnDone := false
		for chunk := range ts {
			if chunk.Err != nil {
				res.Answer = turnText.String()
				res.Err = chunk.Err
				return res
			}
			if chunk.Done {
				turnDone = true
				res.Usage = chunk.Usage
				toolCalls = chunk.ToolCalls
				break
			}
			if chunk.Reasoning != "" {
				if p.StreamReasoning {
					emit("thinking", mustJSON(map[string]string{"delta": chunk.Reasoning}))
				}
				continue
			}
			// Stream answer content live, but only KEEP it as the final answer once
			// we know the turn is final (no tool_calls). Buffer per-turn so pre-tool
			// chatter never lands in the persisted answer.
			turnText.WriteString(chunk.Delta)
			emit("", mustJSON(map[string]string{"delta": chunk.Delta}))
		}

		// Client aborted (ctx cancelled) — stop quietly, persisting the partial.
		if !turnDone && ctx.Err() != nil {
			res.Answer = turnText.String()
			return res
		}

		if len(toolCalls) == 0 {
			// Final answer for this request.
			res.Answer = turnText.String()
			res.Completed = turnDone
			return res
		}

		for i := range toolCalls {
			toolCalls[i] = normalizeToolCall(toolCalls[i], iter, i)
		}

		// The model asked for tools. Append the assistant turn that requested them
		// (OpenAI requires the tool_calls message to precede the tool results),
		// then run each call and append its result.
		msgs = append(msgs, ports.Message{Role: ports.RoleAssistant, ToolCalls: toolCalls})
		for _, tc := range toolCalls {
			emit("tool_call", mustJSON(map[string]string{"id": tc.ID, "name": tc.Name, "arguments": tc.Arguments}))

			text, isErr := "", false
			tool, ok := reg.lookup(tc.Name)
			kind := tool.Kind
			if strings.TrimSpace(kind) == "" {
				kind = "tool"
			}
			start := time.Now()
			normalizedArgs, argsHash, argErr := normalizeArgs(tc.Arguments)
			if strings.TrimSpace(tc.Name) == "" {
				isErr = true
				text = "Tool call missing function name"
			} else if argErr != nil {
				isErr = true
				text = "Invalid tool arguments: " + argErr.Error()
			} else if !ok {
				isErr = true
				text = "Tool not available: " + tc.Name
			} else {
				t, ierr, cerr := tool.Invoke(ctx, normalizedArgs)
				if cerr != nil {
					isErr = true
					text = "Tool call failed: " + cerr.Error()
				} else {
					text, isErr = t, ierr
				}
			}
			emit("tool_result", mustJSON(map[string]any{
				"id": tc.ID, "name": tc.Name, "ok": !isErr, "preview": truncPreview(text, 500),
			}))

			res.ToolExecutions = append(res.ToolExecutions, ToolExecution{
				ID:          tc.ID,
				Name:        tc.Name,
				Kind:        kind,
				OK:          !isErr,
				LatencyMS:   time.Since(start).Milliseconds(),
				Error:       toolErrorSummary(isErr, text),
				ArgsSHA256:  argsHash,
				ResultChars: len([]rune(text)),
			})

			// Feed the full result back to the model (a tool message per call).
			msgs = append(msgs, ports.Message{Role: ports.RoleTool, ToolCallID: tc.ID, Content: text})
		}

		// If this was the last allowed iteration and tools are STILL pending, note
		// it and stop (guard against an unbounded loop).
		if iter == maxIters-1 {
			note := p.IterLimitThinkingNote
			if note == "" {
				note = "\n(Tool call limit reached.)"
			}
			emit("thinking", mustJSON(map[string]string{"delta": note}))
			if res.Answer == "" && p.IterLimitNote != "" {
				res.Answer = p.IterLimitNote
				emit("", mustJSON(map[string]string{"delta": p.IterLimitNote}))
			}
			res.Completed = true
		}
	}
	return res
}

func normalizeToolCall(tc ports.ToolCall, iter, idx int) ports.ToolCall {
	if strings.TrimSpace(tc.ID) != "" {
		return tc
	}
	sum := sha256.Sum256([]byte(fmt.Sprintf("%d:%d:%s:%s", iter, idx, tc.Name, tc.Arguments)))
	tc.ID = "call_" + hex.EncodeToString(sum[:6])
	return tc
}

func normalizeArgs(raw string) (json.RawMessage, string, error) {
	trimmed := strings.TrimSpace(raw)
	if trimmed == "" {
		trimmed = "{}"
	}
	dec := json.NewDecoder(strings.NewReader(trimmed))
	dec.UseNumber()
	var obj map[string]any
	if err := dec.Decode(&obj); err != nil {
		return nil, "", err
	}
	if obj == nil {
		return nil, "", fmt.Errorf("arguments must be a JSON object")
	}
	var extra any
	if err := dec.Decode(&extra); err != io.EOF {
		if err == nil {
			return nil, "", fmt.Errorf("arguments must contain a single JSON object")
		}
		return nil, "", err
	}
	compact, err := json.Marshal(obj)
	if err != nil {
		return nil, "", err
	}
	sum := sha256.Sum256(compact)
	return json.RawMessage(compact), hex.EncodeToString(sum[:]), nil
}

func toolErrorSummary(isErr bool, text string) string {
	if !isErr {
		return ""
	}
	return truncPreview(text, 240)
}

// truncPreview clips a tool result to a short, rune-safe preview for the live
// tool_result SSE event (the FULL result still goes back to the model). Bounds by
// runes so multibyte (Turkish/Jira) text is never cut mid-character.
func truncPreview(s string, max int) string {
	r := []rune(s)
	if len(r) <= max {
		return s
	}
	return string(r[:max]) + "…"
}

// mustJSON marshals v, ignoring the (impossible for these payloads) error.
func mustJSON(v any) []byte {
	b, _ := json.Marshal(v)
	return b
}
