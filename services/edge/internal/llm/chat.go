// SPDX-License-Identifier: Apache-2.0

package llm

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"github.com/alicangunduz/raggie/services/edge/internal/outboundhttp"
	"github.com/alicangunduz/raggie/services/edge/internal/ports"
)

var (
	ErrStreamInterrupted = errors.New("chat stream ended before a terminal marker")
	ErrMalformedStream   = errors.New("chat stream contained malformed JSON")
)

// ChatProvider streams completions from an OpenAI-compatible /v1/chat/completions
// endpoint. The user-facing answer is in delta.content; the model's
// chain-of-thought arrives in a separate delta.reasoning field (streamed first,
// before the answer) and is forwarded as ChatChunk.Reasoning so the handler can
// relay it on a separate SSE channel. Implements ports.ChatProvider.
type ChatProvider struct {
	baseURL   string
	apiKey    string
	model     string
	maxTokens int
	http      *http.Client
	adminHTTP *http.Client
	pool      *pool
}

func NewChatProvider(baseURL, apiKey, model string, maxTokens, maxConcurrency int) *ChatProvider {
	return &ChatProvider{
		baseURL:   baseURL,
		apiKey:    apiKey,
		model:     model,
		maxTokens: maxTokens,
		// Streaming lifetime is governed by the caller context. An http.Client
		// timeout would turn a healthy long answer into a synthetic disconnect;
		// only the wait for the first byte is bounded (the transport's
		// response-header timeout, see WithResponseHeaderTimeout).
		http:      outboundhttp.NewLLMClient(0, 0),
		adminHTTP: outboundhttp.NewLLMClient(10*time.Second, 0),
		pool:      newPool(maxConcurrency),
	}
}

// WithResponseHeaderTimeout sets how long the endpoint may take to send its
// response headers (its first byte) — LLMAAS_RESPONSE_HEADER_TIMEOUT_SECONDS
// or a profile's response_header_timeout_seconds. <= 0 keeps the default.
func (c *ChatProvider) WithResponseHeaderTimeout(d time.Duration) *ChatProvider {
	c.http = outboundhttp.NewLLMClient(0, d)
	c.adminHTTP = outboundhttp.NewLLMClient(10*time.Second, d)
	return c
}

func (c *ChatProvider) Stream(ctx context.Context, req ports.ChatRequest) (<-chan ports.ChatChunk, error) {
	if !c.pool.tryAcquire() {
		return nil, ErrUpstreamBusy
	}

	model := req.Model
	if model == "" {
		model = c.model
	}
	maxTok := req.MaxTokens
	if maxTok == 0 {
		maxTok = c.maxTokens
	}
	body := map[string]any{
		"model":       model,
		"messages":    req.Messages,
		"temperature": req.Temperature,
		"max_tokens":  maxTok,
		"stream":      true,
	}
	// Only send reasoning_effort when set; omitting the key lets the provider use
	// its own default (and keeps non-reasoning models from rejecting it).
	if req.ReasoningEffort != "" {
		body["reasoning_effort"] = req.ReasoningEffort
	}
	// Tool-calling mode: advertise the tools and let the model choose. Only added
	// when the caller passed tools, so a normal completion is byte-for-byte the
	// legacy request (no tools / tool_choice keys at all).
	if len(req.Tools) > 0 {
		tools := make([]map[string]any, len(req.Tools))
		for i, t := range req.Tools {
			fn := map[string]any{"name": t.Name}
			if t.Description != "" {
				fn["description"] = t.Description
			}
			// Parameters is a raw JSON Schema; pass it through verbatim. Fall back
			// to an empty-object schema if a tool advertised none.
			if len(t.Parameters) > 0 {
				fn["parameters"] = json.RawMessage(t.Parameters)
			} else {
				fn["parameters"] = json.RawMessage(`{"type":"object","properties":{}}`)
			}
			tools[i] = map[string]any{"type": "function", "function": fn}
		}
		body["tools"] = tools
		// Default "auto" (model decides); "required" forces >=1 tool call this
		// turn (semi-autonomous: an explicitly enabled mode must actually fire).
		choice := "auto"
		if req.ToolChoice == "required" {
			choice = "required"
		}
		body["tool_choice"] = choice
	}
	payload, _ := json.Marshal(body)
	httpReq, err := http.NewRequestWithContext(ctx, http.MethodPost, c.baseURL+"/chat/completions", bytes.NewReader(payload))
	if err != nil {
		c.pool.release()
		return nil, err
	}
	httpReq.Header.Set("Content-Type", "application/json")
	if c.apiKey != "" {
		httpReq.Header.Set("Authorization", "Bearer "+c.apiKey)
	}
	httpReq.Header.Set("Accept", "text/event-stream")

	resp, err := c.http.Do(httpReq)
	if err != nil {
		c.pool.release()
		return nil, err
	}
	if resp.StatusCode != http.StatusOK {
		_ = resp.Body.Close()
		c.pool.release()
		return nil, fmt.Errorf("chat: unexpected status %d", resp.StatusCode)
	}

	ch := make(chan ports.ChatChunk)
	go func() {
		defer c.pool.release()
		defer resp.Body.Close()
		defer close(ch)

		sc := bufio.NewScanner(resp.Body)
		sc.Buffer(make([]byte, 64*1024), 1024*1024)
		var usage *ports.Usage
		// Tool-call accumulator: the provider streams a tool call's id+name on the
		// FIRST fragment for an index, then appends argument fragments on later
		// chunks for that same index. We reassemble per index and emit one terminal
		// chunk when finish_reason=="tool_calls".
		toolAcc := newToolCallAccumulator()
		finishReason := ""
		sawDoneMarker := false
		send := func(chunk ports.ChatChunk) bool {
			select {
			case <-ctx.Done():
				return false
			case ch <- chunk:
				return true
			}
		}
		for sc.Scan() {
			line := strings.TrimSpace(sc.Text())
			if !strings.HasPrefix(line, "data:") {
				continue
			}
			data := strings.TrimSpace(line[len("data:"):])
			if data == "[DONE]" {
				sawDoneMarker = true
				break
			}
			if data == "" {
				continue
			}
			var ev struct {
				Choices []struct {
					Delta struct {
						Content          string          `json:"content"`
						Reasoning        string          `json:"reasoning"`
						ReasoningContent string          `json:"reasoning_content"`
						Thinking         string          `json:"thinking"`
						ToolCalls        []deltaToolCall `json:"tool_calls"`
					} `json:"delta"`
					FinishReason string `json:"finish_reason"`
				} `json:"choices"`
				Usage *struct {
					PromptTokens     int `json:"prompt_tokens"`
					CompletionTokens int `json:"completion_tokens"`
				} `json:"usage"`
			}
			if err := json.Unmarshal([]byte(data), &ev); err != nil {
				send(ports.ChatChunk{Err: fmt.Errorf("%w: %v", ErrMalformedStream, err)})
				return
			}
			if ev.Usage != nil {
				usage = &ports.Usage{PromptTokens: ev.Usage.PromptTokens, CompletionTokens: ev.Usage.CompletionTokens}
			}
			// A delta carries reasoning (chain-of-thought, streamed first) OR
			// content (answer) OR tool_calls fragments — relay text immediately,
			// accumulate tool_calls until the turn finishes.
			if len(ev.Choices) > 0 {
				if fr := ev.Choices[0].FinishReason; fr != "" {
					finishReason = fr
				}
				for _, tc := range ev.Choices[0].Delta.ToolCalls {
					toolAcc.add(tc)
				}
				if r := firstStreamText(
					ev.Choices[0].Delta.Reasoning,
					ev.Choices[0].Delta.ReasoningContent,
					ev.Choices[0].Delta.Thinking,
				); r != "" {
					if !send(ports.ChatChunk{Reasoning: r}) {
						return
					}
				}
				if c := ev.Choices[0].Delta.Content; c != "" {
					if !send(ports.ChatChunk{Delta: c}) {
						return
					}
				}
			}
		}
		if err := sc.Err(); err != nil {
			if ctx.Err() == nil {
				send(ports.ChatChunk{Err: fmt.Errorf("%w: %v", ErrStreamInterrupted, err)})
			}
			return
		}
		if !sawDoneMarker && finishReason == "" {
			send(ports.ChatChunk{Err: ErrStreamInterrupted})
			return
		}
		// Terminal chunk. When the turn requested tools, hand the handler the fully
		// assembled calls in one shot; otherwise it is the normal end-of-answer.
		done := ports.ChatChunk{Done: true, Usage: usage, FinishReason: finishReason}
		if finishReason == "tool_calls" {
			done.ToolCalls = toolAcc.assemble()
		}
		send(done)
	}()
	return ch, nil
}

func firstStreamText(values ...string) string {
	for _, v := range values {
		if v != "" {
			return v
		}
	}
	return ""
}

// deltaToolCall is one streamed tool_call fragment. id+name+type arrive on the
// first fragment for an index; later fragments for that index carry only an
// arguments slice to be concatenated.
type deltaToolCall struct {
	Index    int    `json:"index"`
	ID       string `json:"id"`
	Type     string `json:"type"`
	Function struct {
		Name      string `json:"name"`
		Arguments string `json:"arguments"`
	} `json:"function"`
}

// toolCallAccumulator reassembles streamed tool_call fragments by index. id and
// name are taken from the first fragment that supplies them; arguments are
// concatenated across fragments. Insertion order is preserved for a stable
// emission order.
type toolCallAccumulator struct {
	order []int
	byIdx map[int]*accTool
}

type accTool struct {
	id   string
	name string
	args strings.Builder
}

func newToolCallAccumulator() *toolCallAccumulator {
	return &toolCallAccumulator{byIdx: map[int]*accTool{}}
}

func (a *toolCallAccumulator) add(tc deltaToolCall) {
	t, ok := a.byIdx[tc.Index]
	if !ok {
		t = &accTool{}
		a.byIdx[tc.Index] = t
		a.order = append(a.order, tc.Index)
	}
	if tc.ID != "" {
		t.id = tc.ID
	}
	if tc.Function.Name != "" {
		t.name = tc.Function.Name
	}
	if tc.Function.Arguments != "" {
		t.args.WriteString(tc.Function.Arguments)
	}
}

func (a *toolCallAccumulator) assemble() []ports.ToolCall {
	out := make([]ports.ToolCall, 0, len(a.order))
	for _, idx := range a.order {
		t := a.byIdx[idx]
		if t.name == "" {
			continue // never emit a nameless call
		}
		out = append(out, ports.ToolCall{ID: t.id, Name: t.name, Arguments: t.args.String()})
	}
	return out
}

// ListModels calls the provider's GET /models (OpenAI-compatible) and returns the
// available model ids. It does NOT consume the chat concurrency pool — it is a
// cheap, infrequent admin/discovery call, not part of the A5-bounded hot path.
// A short timeout keeps a slow provider from hanging the caller.
func (c *ChatProvider) ListModels(ctx context.Context) ([]string, error) {
	httpReq, err := http.NewRequestWithContext(ctx, http.MethodGet, c.baseURL+"/models", nil)
	if err != nil {
		return nil, err
	}
	if c.apiKey != "" {
		httpReq.Header.Set("Authorization", "Bearer "+c.apiKey)
	}
	httpReq.Header.Set("Accept", "application/json")

	resp, err := c.adminHTTP.Do(httpReq)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("models: unexpected status %d", resp.StatusCode)
	}

	var body struct {
		Data []struct {
			ID string `json:"id"`
		} `json:"data"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		return nil, err
	}
	_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 4<<10))
	ids := make([]string, 0, len(body.Data))
	for _, m := range body.Data {
		if m.ID != "" {
			ids = append(ids, m.ID)
		}
	}
	return ids, nil
}

// Ready verifies that the configured default model is currently advertised by
// the OpenAI-compatible provider.
func (c *ChatProvider) Ready(ctx context.Context) error {
	return c.ReadyModel(ctx, c.model)
}

// ReadyModel verifies that one provider-native model is advertised.
func (c *ChatProvider) ReadyModel(ctx context.Context, model string) error {
	ids, err := c.ListModels(ctx)
	if err != nil {
		return err
	}
	for _, id := range ids {
		if id == model {
			return nil
		}
	}
	return fmt.Errorf("configured chat model %q is unavailable", model)
}

var _ ports.ChatProvider = (*ChatProvider)(nil)
