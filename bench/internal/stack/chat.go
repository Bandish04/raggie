// SPDX-License-Identifier: Apache-2.0

package stack

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"strings"
	"time"

	"github.com/alicangunduz/raggie/bench/internal/sse"
)

// ChatRequest is the subset of the edge's POST /api/v1/chat/stream body the
// harnesses send. An empty ConversationID starts a new conversation.
type ChatRequest struct {
	WorkspaceID    string `json:"workspace_id"`
	Message        string `json:"message"`
	ConversationID string `json:"conversation_id,omitempty"`
	Locale         string `json:"locale,omitempty"`
}

// Source is one retrieved chunk from the `sources` event.
type Source struct {
	DocumentID string  `json:"document_id"`
	Filename   string  `json:"filename"`
	ChunkIndex int     `json:"chunk_index"`
	Score      float32 `json:"score"`
}

// ChatResult is one instrumented chat turn. Phase offsets are measured from
// the moment the request was sent; a zero offset means the phase never came.
//
// On the edge the whole retrieval (embed → hybrid search → rerank) runs before
// the response headers are written, together with persisting the user turn and
// opening the LLM stream; Headers and Meta are therefore an upper bound of the
// retrieval latency, and Sources follows immediately after.
type ChatResult struct {
	Status       int    // HTTP status (0 = transport error)
	ErrorCode    string // pre-stream error code, or the SSE `error` event code
	Err          error  // transport/protocol error
	Headers      time.Duration
	Meta         time.Duration
	Sources      time.Duration
	FirstToken   time.Duration
	Done         time.Duration // the `done` event (completed and persisted)
	Total        time.Duration // stream fully read
	Tokens       int
	Answer       string
	SourceList   []Source
	Conversation string
	MessageID    string
}

// OK reports a fully completed turn: HTTP 200, a `done` event and no error.
func (r ChatResult) OK() bool {
	return r.Status == http.StatusOK && r.Err == nil && r.ErrorCode == "" && r.Done > 0
}

// Outcome classifies the turn for error breakdowns.
func (r ChatResult) Outcome() string {
	switch {
	case r.OK():
		return "ok"
	case r.Err != nil && errors.Is(r.Err, context.DeadlineExceeded):
		return "timeout"
	case r.Err != nil && r.Status == 0:
		return "transport_error"
	case r.Status != http.StatusOK && r.ErrorCode != "":
		return "http_" + http.StatusText(r.Status) + ":" + r.ErrorCode
	case r.Status != http.StatusOK:
		return "http_" + http.StatusText(r.Status)
	case r.ErrorCode != "":
		return "stream_error:" + r.ErrorCode
	case r.Err != nil:
		return "stream_broken"
	default:
		return "incomplete"
	}
}

// Chat sends one turn and reads the SSE stream to the end, recording when
// each phase arrived. It never returns an error: failures are in the result.
func (c *Client) Chat(ctx context.Context, in ChatRequest) ChatResult {
	var res ChatResult
	body, _ := json.Marshal(in)
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.Edge+"/api/v1/chat/stream", bytes.NewReader(body))
	if err != nil {
		res.Err = err
		return res
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "text/event-stream")
	if c.Token != "" {
		req.Header.Set("Authorization", "Bearer "+c.Token)
	}
	start := time.Now()
	resp, err := c.HTTP.Do(req)
	if err != nil {
		res.Err = err
		return res
	}
	defer resp.Body.Close()
	res.Status = resp.StatusCode
	res.Headers = time.Since(start)
	if resp.StatusCode != http.StatusOK {
		var ae *APIError
		if errors.As(apiError(req, resp), &ae) {
			res.ErrorCode = ae.Code
		}
		return res
	}

	var answer strings.Builder
	err = sse.Read(resp.Body, func(e sse.Event) error {
		at := e.At.Sub(start)
		switch e.Name {
		case "meta":
			var m struct {
				ConversationID string `json:"conversation_id"`
				MessageID      string `json:"message_id"`
			}
			_ = json.Unmarshal([]byte(e.Data), &m)
			res.Meta, res.Conversation, res.MessageID = at, m.ConversationID, m.MessageID
		case "sources":
			var s struct {
				Sources []Source `json:"sources"`
			}
			if json.Unmarshal([]byte(e.Data), &s) == nil {
				res.SourceList = s.Sources
			}
			res.Sources = at
		case "error":
			var s struct {
				Code string `json:"code"`
			}
			_ = json.Unmarshal([]byte(e.Data), &s)
			res.ErrorCode = s.Code
			if res.ErrorCode == "" {
				res.ErrorCode = "stream_error"
			}
		case "done":
			var d struct {
				MessageID string `json:"message_id"`
			}
			if json.Unmarshal([]byte(e.Data), &d) == nil && d.MessageID != "" {
				res.MessageID = d.MessageID
			}
			res.Done = at
		case "message":
			if e.Data == "[DONE]" {
				return nil
			}
			var t struct {
				Delta string `json:"delta"`
			}
			if json.Unmarshal([]byte(e.Data), &t) != nil || t.Delta == "" {
				return nil
			}
			if res.FirstToken == 0 {
				res.FirstToken = at
			}
			res.Tokens++
			answer.WriteString(t.Delta)
		}
		return nil
	})
	res.Total = time.Since(start)
	res.Answer = answer.String()
	if err != nil {
		res.Err = err
	}
	return res
}
