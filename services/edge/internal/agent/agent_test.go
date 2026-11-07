// SPDX-License-Identifier: Apache-2.0

package agent

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"sync/atomic"
	"testing"

	"github.com/alicangunduz/raggie/services/edge/internal/ports"
)

var errTestStream = errors.New("stream interrupted")

// scriptChatProvider streams a tool-call turn on call #1, then a final answer on
// call #2 (one agentic iteration). It records how many times it was called and
// whether the 2nd request carried a role:tool message and the ToolChoice.
type scriptChatProvider struct {
	calls        atomic.Int32
	sawToolMsg   atomic.Bool
	lastChoice   atomic.Value // string
	emitToolCall bool
}

func (p *scriptChatProvider) Stream(ctx context.Context, req ports.ChatRequest) (<-chan ports.ChatChunk, error) {
	n := p.calls.Add(1)
	p.lastChoice.Store(req.ToolChoice)
	if n == 2 {
		for _, m := range req.Messages {
			if m.Role == ports.RoleTool {
				p.sawToolMsg.Store(true)
			}
		}
	}
	ch := make(chan ports.ChatChunk)
	go func() {
		defer close(ch)
		if p.emitToolCall && n == 1 {
			ch <- ports.ChatChunk{Reasoning: "thinking"}
			ch <- ports.ChatChunk{
				Done:         true,
				FinishReason: "tool_calls",
				ToolCalls:    []ports.ToolCall{{ID: "c1", Name: "echo", Arguments: `{"x":"hi"}`}},
				Usage:        &ports.Usage{CompletionTokens: 1},
			}
			return
		}
		ch <- ports.ChatChunk{Delta: "final answer"}
		ch <- ports.ChatChunk{Done: true, FinishReason: "stop", Usage: &ports.Usage{CompletionTokens: 2}}
	}()
	return ch, nil
}

// collectEmit records emitted events for assertions.
func collectEmit(events *[]string) Emit {
	return func(event string, data []byte) {
		*events = append(*events, event+"|"+string(data))
	}
}

// With an EMPTY registry, Run makes exactly ONE Stream call and relays content +
// reasoning — the legacy single-stream path.
func TestRunNoToolsSingleStream(t *testing.T) {
	chat := &scriptChatProvider{emitToolCall: false}
	var events []string
	res := Run(context.Background(), RunParams{
		Chat:          chat,
		Messages:      []ports.Message{{Role: ports.RoleUser, Content: "hi"}},
		MaxIterations: 4,
	}, collectEmit(&events))

	if chat.calls.Load() != 1 {
		t.Fatalf("expected exactly 1 Stream call with no tools, got %d", chat.calls.Load())
	}
	if res.Answer != "final answer" || !res.Completed {
		t.Fatalf("expected completed final answer, got %q completed=%v", res.Answer, res.Completed)
	}
	// No tools advertised ⇒ ToolChoice never set on the request.
	if c, _ := chat.lastChoice.Load().(string); c != "" {
		t.Fatalf("expected no tool_choice with empty registry, got %q", c)
	}
}

type interruptedChatProvider struct{}

func (interruptedChatProvider) Stream(context.Context, ports.ChatRequest) (<-chan ports.ChatChunk, error) {
	ch := make(chan ports.ChatChunk, 2)
	ch <- ports.ChatChunk{Delta: "partial answer"}
	ch <- ports.ChatChunk{Err: errTestStream}
	close(ch)
	return ch, nil
}

func TestRunPropagatesTerminalStreamErrorAndKeepsPartialAnswer(t *testing.T) {
	var events []string
	res := Run(context.Background(), RunParams{
		Chat:          interruptedChatProvider{},
		Messages:      []ports.Message{{Role: ports.RoleUser, Content: "hi"}},
		MaxIterations: 1,
	}, collectEmit(&events))

	if !errors.Is(res.Err, errTestStream) {
		t.Fatalf("expected terminal stream error, got %v", res.Err)
	}
	if res.Completed {
		t.Fatal("interrupted stream must not be completed")
	}
	if res.Answer != "partial answer" {
		t.Fatalf("expected partial answer to be retained, got %q", res.Answer)
	}
}

// With a tool registry, Run invokes the requested tool, emits tool_call +
// tool_result, feeds the result back, and the next turn is the final answer.
func TestRunWithToolsInvokesAndLoops(t *testing.T) {
	chat := &scriptChatProvider{emitToolCall: true}
	var invokedWith string
	reg := NewRegistry(Tool{
		Spec: ports.ToolSpec{Name: "echo", Description: "echo", Parameters: json.RawMessage(`{"type":"object"}`)},
		Invoke: func(ctx context.Context, args json.RawMessage) (string, bool, error) {
			invokedWith = string(args)
			return "echoed: hi", false, nil
		},
	})
	var events []string
	res := RunWithTools(context.Background(), reg, RunParams{
		Chat:            chat,
		Messages:        []ports.Message{{Role: ports.RoleUser, Content: "echo hi"}},
		ToolChoice:      "required",
		MaxIterations:   4,
		StreamReasoning: true,
	}, collectEmit(&events))

	if chat.calls.Load() != 2 {
		t.Fatalf("expected 2 Stream calls (tool turn + final), got %d", chat.calls.Load())
	}
	if !strings.Contains(invokedWith, `"x":"hi"`) {
		t.Fatalf("tool invoked with unexpected args: %q", invokedWith)
	}
	if !chat.sawToolMsg.Load() {
		t.Fatal("expected the 2nd request to carry a role:tool message")
	}
	if res.Answer != "final answer" || !res.Completed {
		t.Fatalf("expected completed final answer, got %q completed=%v", res.Answer, res.Completed)
	}
	if c, _ := chat.lastChoice.Load().(string); c != "required" {
		t.Fatalf("expected tool_choice=required forwarded, got %q", c)
	}
	joined := strings.Join(events, "\n")
	if !strings.Contains(joined, "thinking|") {
		t.Fatalf("expected a thinking event, got:\n%s", joined)
	}
	if !strings.Contains(joined, "tool_call|") || !strings.Contains(joined, "tool_result|") {
		t.Fatalf("expected tool_call + tool_result events, got:\n%s", joined)
	}
	if !strings.Contains(joined, `"ok":true`) || !strings.Contains(joined, "echoed: hi") {
		t.Fatalf("expected tool_result with ok:true and preview, got:\n%s", joined)
	}
}

// An unknown tool name (not in the registry) yields a tool_result with ok:false
// and the loop still continues with the error fed back.
func TestRunUnknownToolIsErrorResult(t *testing.T) {
	chat := &scriptChatProvider{emitToolCall: true}
	reg := NewRegistry() // empty: the model's "echo" call has no matching tool
	var events []string
	// With an empty registry, Run does a single stream (no tools advertised), so
	// force the tool path by advertising a different tool the model won't be asked
	// for is not possible here; instead test lookup miss via a registry whose only
	// tool has a different name.
	reg.Add(Tool{
		Spec:   ports.ToolSpec{Name: "other", Parameters: json.RawMessage(`{}`)},
		Invoke: func(ctx context.Context, a json.RawMessage) (string, bool, error) { return "x", false, nil },
	})
	res := RunWithTools(context.Background(), reg, RunParams{
		Chat:          chat,
		Messages:      []ports.Message{{Role: ports.RoleUser, Content: "go"}},
		MaxIterations: 4,
	}, collectEmit(&events))

	joined := strings.Join(events, "\n")
	if !strings.Contains(joined, `"ok":false`) {
		t.Fatalf("expected an ok:false tool_result for an unknown tool, got:\n%s", joined)
	}
	if res.Answer != "final answer" {
		t.Fatalf("expected the loop to continue to the final answer, got %q", res.Answer)
	}
}

type invalidArgsChatProvider struct {
	calls      atomic.Int32
	toolMsgID  atomic.Value // string
	toolMsgRaw atomic.Value // string
}

func (p *invalidArgsChatProvider) Stream(ctx context.Context, req ports.ChatRequest) (<-chan ports.ChatChunk, error) {
	n := p.calls.Add(1)
	if n == 2 {
		for _, m := range req.Messages {
			if m.Role == ports.RoleTool {
				p.toolMsgID.Store(m.ToolCallID)
				p.toolMsgRaw.Store(m.Content)
			}
		}
	}
	ch := make(chan ports.ChatChunk)
	go func() {
		defer close(ch)
		if n == 1 {
			ch <- ports.ChatChunk{
				Done:         true,
				FinishReason: "tool_calls",
				ToolCalls: []ports.ToolCall{
					{Name: "echo", Arguments: `["not","an","object"]`},
				},
			}
			return
		}
		ch <- ports.ChatChunk{Delta: "final after invalid args"}
		ch <- ports.ChatChunk{Done: true, FinishReason: "stop"}
	}()
	return ch, nil
}

func TestRunRejectsInvalidToolArgumentsAndSynthesizesID(t *testing.T) {
	chat := &invalidArgsChatProvider{}
	var invoked atomic.Bool
	reg := NewRegistry(Tool{
		Spec: ports.ToolSpec{Name: "echo", Parameters: json.RawMessage(`{"type":"object"}`)},
		Invoke: func(ctx context.Context, args json.RawMessage) (string, bool, error) {
			invoked.Store(true)
			return "should not run", false, nil
		},
	})
	var events []string
	res := RunWithTools(context.Background(), reg, RunParams{
		Chat:          chat,
		Messages:      []ports.Message{{Role: ports.RoleUser, Content: "go"}},
		MaxIterations: 3,
	}, collectEmit(&events))

	if invoked.Load() {
		t.Fatal("tool invoke must not run for non-object JSON arguments")
	}
	if res.Answer != "final after invalid args" || !res.Completed {
		t.Fatalf("expected final answer after invalid args, got %q completed=%v", res.Answer, res.Completed)
	}
	if len(res.ToolExecutions) != 1 {
		t.Fatalf("expected 1 tool execution audit row, got %+v", res.ToolExecutions)
	}
	exec := res.ToolExecutions[0]
	if exec.ID == "" || exec.OK || !strings.Contains(exec.Error, "Invalid tool arguments") {
		t.Fatalf("unexpected tool execution audit: %+v", exec)
	}
	if id, _ := chat.toolMsgID.Load().(string); id == "" || id != exec.ID {
		t.Fatalf("expected synthesized id to be fed back as tool_call_id, got %q audit=%q", id, exec.ID)
	}
	if raw, _ := chat.toolMsgRaw.Load().(string); !strings.Contains(raw, "Invalid tool arguments") {
		t.Fatalf("expected invalid-args message fed back to model, got %q", raw)
	}
	joined := strings.Join(events, "\n")
	if !strings.Contains(joined, `"ok":false`) || !strings.Contains(joined, `"id":"`+exec.ID+`"`) {
		t.Fatalf("expected ok:false tool_result with synthesized id, got:\n%s", joined)
	}
}

// Raw chain-of-thought is NOT relayed unless the operator opts in
// (STREAM_REASONING): it can leak retrieved context or prompt fragments.
func TestRunWithToolsSuppressesReasoningByDefault(t *testing.T) {
	chat := &scriptChatProvider{emitToolCall: true}
	reg := NewRegistry()
	reg.Add(Tool{
		Kind: "test",
		Spec: ports.ToolSpec{Name: "echo", Parameters: json.RawMessage(`{"type":"object"}`)},
		Invoke: func(_ context.Context, _ json.RawMessage) (string, bool, error) {
			return "ok", false, nil
		},
	})
	var events []string
	res := RunWithTools(context.Background(), reg, RunParams{
		Chat:          chat,
		Messages:      []ports.Message{{Role: ports.RoleUser, Content: "echo hi"}},
		ToolChoice:    "auto",
		MaxIterations: 4,
	}, collectEmit(&events))
	if !res.Completed || res.Answer != "final answer" {
		t.Fatalf("unexpected result: %+v", res)
	}
	for _, e := range events {
		if strings.HasPrefix(e, "thinking|") {
			t.Fatalf("reasoning leaked to the client by default: %q", e)
		}
	}
}
