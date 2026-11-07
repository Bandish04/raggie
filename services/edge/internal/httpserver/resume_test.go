// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"regexp"
	"strings"
	"testing"
	"time"

	"github.com/alicangunduz/raggie/services/edge/internal/ports/mock"
	"github.com/alicangunduz/raggie/services/edge/internal/rag"
	"github.com/alicangunduz/raggie/services/edge/internal/widgetauth"
)

var metaMessageRe = regexp.MustCompile(`event: meta\ndata: (\{[^\n]*\})`)

type metaEvent struct {
	ConversationID string `json:"conversation_id"`
	MessageID      string `json:"message_id"`
}

func firstMeta(t *testing.T, body string) metaEvent {
	t.Helper()
	m := metaMessageRe.FindStringSubmatch(body)
	if m == nil {
		t.Fatalf("no meta event:\n%s", body)
	}
	var ev metaEvent
	if err := json.Unmarshal([]byte(m[1]), &ev); err != nil {
		t.Fatal(err)
	}
	return ev
}

type principalReq struct {
	auth, origin string
}

func (f idorFixture) internalPrincipal(t *testing.T, user string) principalReq {
	return principalReq{auth: "Bearer " + adminToken(t, "STAFF", user)}
}

func (f idorFixture) widgetPrincipal(t *testing.T) principalReq {
	tok, _ := widgetauth.Mint("test-secret", f.extWS, 30*time.Minute, time.Now())
	return principalReq{auth: "Bearer " + tok, origin: "https://acme.example"}
}

func (p principalReq) post(srv *http.Server, body string) *httptest.ResponseRecorder {
	req := httptest.NewRequest(http.MethodPost, "/api/v1/chat/stream", strings.NewReader(body))
	req.Header.Set("Authorization", p.auth)
	if p.origin != "" {
		req.Header.Set("Origin", p.origin)
	}
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)
	return rec
}

// drainedTurn streams a question that is cut off by a forced shutdown drain
// and returns the response body.
func (f idorFixture) drainedTurn(t *testing.T, p principalReq, body string) string {
	return f.drainedTurnCfg(t, p, body, false)
}

func (f idorFixture) drainedTurnCfg(t *testing.T, p principalReq, body string, unified bool) string {
	t.Helper()
	chat := newGatedChat()
	d := NewDrainer()
	cfg := widgetCfg()
	cfg.HistoryMaxMessages = 16
	cfg.AgentUnifiedLoop = unified
	srv := newSrvWithCfg(t, cfg, Deps{
		RAG: rag.New(mock.QueryEmbedder{Dim: 8}, mock.VectorStore{}), Chat: chat,
		Store: f.st, WSInfo: f.st, Drain: d,
	})
	done := make(chan *httptest.ResponseRecorder, 1)
	go func() { done <- p.post(srv, body) }()
	<-chat.started
	d.StartDrain()
	d.CancelAll()
	select {
	case rec := <-done:
		return rec.Body.String()
	case <-time.After(5 * time.Second):
		t.Fatal("drained turn did not finish")
		return ""
	}
}

func (f idorFixture) messageRow(t *testing.T, id string) (sender, content string, partial bool, interrupted string) {
	t.Helper()
	if err := f.pool.QueryRow(context.Background(),
		"SELECT sender, content, partial, COALESCE(interrupted_reason,'') FROM messages WHERE id=$1::uuid", id,
	).Scan(&sender, &content, &partial, &interrupted); err != nil {
		t.Fatal(err)
	}
	return
}

func (f idorFixture) countSender(t *testing.T, conv, sender string) int {
	t.Helper()
	var n int
	if err := f.pool.QueryRow(context.Background(),
		"SELECT count(*) FROM messages WHERE conversation_id=$1::uuid AND sender=$2", conv, sender).Scan(&n); err != nil {
		t.Fatal(err)
	}
	return n
}

func TestResumeAfterDrain(t *testing.T) {
	f := newIDORFixture(t)
	for _, tc := range []struct {
		name string
		p    principalReq
		ws   string
	}{
		{"internal user", f.internalPrincipal(t, f.alice), f.intWS},
		{"widget session", f.widgetPrincipal(t), f.extWS},
	} {
		t.Run(tc.name, func(t *testing.T) {
			question := "what is the leave policy " + tc.name
			out := f.drainedTurn(t, tc.p, `{"workspace_id":"`+tc.ws+`","message":"`+question+`"}`)

			// The assistant message id is announced up front and repeated on reconnect.
			meta := firstMeta(t, out)
			if meta.MessageID == "" || meta.ConversationID == "" {
				t.Fatalf("meta must carry conversation_id and message_id: %+v", meta)
			}
			if !strings.Contains(out, "event: reconnect") || !strings.Contains(out, `"message_id":"`+meta.MessageID+`"`) {
				t.Fatalf("reconnect event must name the interrupted message:\n%s", out)
			}
			sender, content, partial, interrupted := f.messageRow(t, meta.MessageID)
			if sender != "BOT" || !partial || interrupted != "shutdown_drain" || !strings.Contains(content, "partial") {
				t.Fatalf("drained answer not marked interrupted: %s %q partial=%v interrupted=%q", sender, content, partial, interrupted)
			}
			users, bots := f.countSender(t, meta.ConversationID, "USER"), f.countSender(t, meta.ConversationID, "BOT")

			// Resume: no message text needed; the stored question is reused.
			chat := &recordingChat{}
			srv := f.server(t, chat)
			rec := tc.p.post(srv, `{"workspace_id":"`+tc.ws+`","conversation_id":"`+meta.ConversationID+
				`","resume_message_id":"`+meta.MessageID+`"}`)
			if rec.Code != http.StatusOK {
				t.Fatalf("resume: %d %s", rec.Code, rec.Body.String())
			}
			if m := firstMeta(t, rec.Body.String()); m.MessageID != meta.MessageID || m.ConversationID != meta.ConversationID {
				t.Fatalf("resume must continue the same message: %+v vs %+v", m, meta)
			}
			if got := strings.Count(chat.prompts(), question); got != 1 {
				t.Fatalf("question should appear exactly once in the prompt, got %d:\n%s", got, chat.prompts())
			}
			if f.countSender(t, meta.ConversationID, "USER") != users || f.countSender(t, meta.ConversationID, "BOT") != bots {
				t.Fatal("resume must not append new USER/BOT rows")
			}
			_, content, partial, interrupted = f.messageRow(t, meta.MessageID)
			if partial || interrupted != "" || strings.TrimSpace(content) != "ok" {
				t.Fatalf("resumed message not overwritten: %q partial=%v interrupted=%q", content, partial, interrupted)
			}

			// Resuming the same id again is no longer allowed (not interrupted).
			if rec := tc.p.post(f.server(t, &recordingChat{}), `{"workspace_id":"`+tc.ws+`","resume_message_id":"`+meta.MessageID+`"}`); rec.Code != http.StatusBadRequest {
				t.Fatalf("second resume: expected 400, got %d", rec.Code)
			}
		})
	}
}

func TestResumeRejections(t *testing.T) {
	f := newIDORFixture(t)
	alice := f.internalPrincipal(t, f.alice)
	out := f.drainedTurn(t, alice, `{"workspace_id":"`+f.intWS+`","message":"cut off"}`)
	meta := firstMeta(t, out)

	cases := []struct {
		name string
		p    principalReq
		body string
		want int
	}{
		{"other user", f.internalPrincipal(t, f.bob), `{"workspace_id":"` + f.intWS + `","resume_message_id":"` + meta.MessageID + `"}`, http.StatusNotFound},
		{"widget session of another visitor", f.widgetPrincipal(t), `{"workspace_id":"` + f.extWS + `","resume_message_id":"` + meta.MessageID + `"}`, http.StatusNotFound},
		{"conversation id mismatch", alice, `{"workspace_id":"` + f.intWS + `","conversation_id":"` + f.aliceConv + `","resume_message_id":"` + meta.MessageID + `"}`, http.StatusNotFound},
		{"unknown id", alice, `{"workspace_id":"` + f.intWS + `","resume_message_id":"00000000-0000-4000-8000-000000000000"}`, http.StatusNotFound},
		{"malformed id", alice, `{"workspace_id":"` + f.intWS + `","resume_message_id":"nope"}`, http.StatusBadRequest},
	}
	for _, tc := range cases {
		if rec := tc.p.post(f.server(t, &recordingChat{}), tc.body); rec.Code != tc.want {
			t.Fatalf("%s: expected %d, got %d (%s)", tc.name, tc.want, rec.Code, rec.Body.String())
		}
	}
	if _, _, _, interrupted := f.messageRow(t, meta.MessageID); interrupted != "shutdown_drain" {
		t.Fatal("rejected resumes must not consume the interrupted marker")
	}

	// A completed (not interrupted) answer cannot be resumed.
	srv := f.server(t, &recordingChat{})
	done := alice.post(srv, `{"workspace_id":"`+f.intWS+`","conversation_id":"`+meta.ConversationID+`","message":"next question"}`)
	completed := firstMeta(t, done.Body.String())
	if rec := alice.post(srv, `{"workspace_id":"`+f.intWS+`","resume_message_id":"`+completed.MessageID+`"}`); rec.Code != http.StatusBadRequest {
		t.Fatalf("completed message: expected 400, got %d", rec.Code)
	}
	// The interrupted one is no longer the last turn.
	if rec := alice.post(srv, `{"workspace_id":"`+f.intWS+`","resume_message_id":"`+meta.MessageID+`"}`); rec.Code != http.StatusBadRequest {
		t.Fatalf("not last turn: expected 400, got %d", rec.Code)
	}
}

// The unified agentic path announces, marks and resumes the turn the same way.
func TestResumeAfterDrainUnified(t *testing.T) {
	f := newIDORFixture(t)
	alice := f.internalPrincipal(t, f.alice)
	out := f.drainedTurnCfg(t, alice, `{"workspace_id":"`+f.intWS+`","message":"unified question"}`, true)
	meta := firstMeta(t, out)
	if _, _, partial, interrupted := f.messageRow(t, meta.MessageID); !partial || interrupted != "shutdown_drain" {
		t.Fatalf("unified drained turn not marked: partial=%v interrupted=%q", partial, interrupted)
	}
	chat := &recordingChat{}
	cfg := widgetCfg()
	cfg.HistoryMaxMessages = 16
	cfg.AgentUnifiedLoop = true
	srv := newSrvWithCfg(t, cfg, Deps{
		RAG: rag.New(mock.QueryEmbedder{Dim: 8}, mock.VectorStore{}), Chat: chat, Store: f.st, WSInfo: f.st,
	})
	rec := alice.post(srv, `{"workspace_id":"`+f.intWS+`","resume_message_id":"`+meta.MessageID+`"}`)
	if rec.Code != http.StatusOK || firstMeta(t, rec.Body.String()).MessageID != meta.MessageID {
		t.Fatalf("unified resume: %d %s", rec.Code, rec.Body.String())
	}
	if strings.Count(chat.prompts(), "unified question") != 1 {
		t.Fatalf("question duplicated in prompt:\n%s", chat.prompts())
	}
	if _, _, partial, interrupted := f.messageRow(t, meta.MessageID); partial || interrupted != "" {
		t.Fatal("unified resume did not finalize the turn")
	}
}

// A turn that fails before streaming starts leaves no empty assistant row.
func TestPreStreamFailureDiscardsPlaceholder(t *testing.T) {
	f := newIDORFixture(t)
	cfg := widgetCfg()
	srv := newSrvWithCfg(t, cfg, Deps{
		RAG: rag.New(mock.QueryEmbedder{Dim: 8}, mock.VectorStore{}), Chat: failingChat{}, Store: f.st, WSInfo: f.st,
	})
	rec := f.internalPrincipal(t, f.alice).post(srv, `{"workspace_id":"`+f.intWS+`","conversation_id":"`+f.aliceConv+`","message":"boom"}`)
	if rec.Code != http.StatusBadGateway {
		t.Fatalf("expected 502, got %d", rec.Code)
	}
	var empty int
	if err := f.pool.QueryRow(context.Background(),
		"SELECT count(*) FROM messages WHERE conversation_id=$1::uuid AND sender='BOT' AND content=''", f.aliceConv,
	).Scan(&empty); err != nil {
		t.Fatal(err)
	}
	if empty != 0 {
		t.Fatalf("%d empty placeholder rows left behind", empty)
	}
}
