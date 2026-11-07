// SPDX-License-Identifier: Apache-2.0

package llm

import (
	"bytes"
	"context"
	"io"
	"net/http"
	"testing"
	"time"

	"github.com/alicangunduz/raggie/services/edge/internal/ports"
)

// staticTransport answers every request with a fixed 200 SSE body.
type staticTransport struct{ body []byte }

func (s staticTransport) RoundTrip(*http.Request) (*http.Response, error) {
	return &http.Response{
		StatusCode: http.StatusOK,
		Header:     http.Header{"Content-Type": []string{"text/event-stream"}},
		Body:       io.NopCloser(bytes.NewReader(s.body)),
	}, nil
}

// Arbitrary upstream SSE bodies never panic the stream parser, the stream
// always terminates with exactly one terminal chunk (Done or Err) as its last
// element, and the concurrency slot is always released.
func FuzzChatStreamParsing(f *testing.F) {
	for _, s := range []string{
		"data: {\"choices\":[{\"delta\":{\"content\":\"hi\"}}]}\n\ndata: [DONE]\n\n",
		"data: {\"choices\":[{\"delta\":{\"reasoning\":\"r\"},\"finish_reason\":null}]}\ndata: {\"choices\":[{\"delta\":{},\"finish_reason\":\"stop\"}],\"usage\":{\"prompt_tokens\":1,\"completion_tokens\":2}}\n",
		"data: {\"choices\":[{\"delta\":{\"tool_calls\":[{\"index\":0,\"id\":\"c\",\"function\":{\"name\":\"t\",\"arguments\":\"{\\\"a\\\"\"}}]}}]}\ndata: {\"choices\":[{\"delta\":{\"tool_calls\":[{\"index\":0,\"function\":{\"arguments\":\":1}\"}}]},\"finish_reason\":\"tool_calls\"}]}\n",
		"data: {not json}\n",
		"data:\n\n: comment\nevent: x\n",
		"",
	} {
		f.Add([]byte(s))
	}
	f.Fuzz(func(t *testing.T, body []byte) {
		if len(body) > 256<<10 {
			return
		}
		c := NewChatProvider("http://upstream.invalid/v1", "", "m", 64, 1)
		c.http = &http.Client{Transport: staticTransport{body: body}}
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		stream, err := c.Stream(ctx, ports.ChatRequest{Messages: []ports.Message{{Role: ports.RoleUser, Content: "q"}}})
		if err != nil {
			t.Fatalf("stream start: %v", err)
		}
		var chunks []ports.ChatChunk
		for ch := range stream {
			chunks = append(chunks, ch)
		}
		if ctx.Err() != nil {
			t.Fatal("stream did not terminate")
		}
		if len(chunks) == 0 {
			t.Fatal("stream closed without a terminal chunk")
		}
		for i, ch := range chunks {
			terminal := ch.Done || ch.Err != nil
			if terminal != (i == len(chunks)-1) {
				t.Fatalf("terminal chunk at %d of %d: %+v", i, len(chunks), ch)
			}
			for _, tc := range ch.ToolCalls {
				if tc.Name == "" {
					t.Fatalf("nameless tool call emitted: %+v", tc)
				}
			}
		}
		// The single pool slot must be free again (released just after the
		// channel closes, so allow a brief moment).
		deadline := time.Now().Add(time.Second)
		for !c.pool.tryAcquire() {
			if time.Now().After(deadline) {
				t.Fatal("concurrency slot leaked")
			}
			time.Sleep(time.Millisecond)
		}
		c.pool.release()
	})
}
