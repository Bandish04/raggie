// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"context"
	"net/http"
	"net/http/httptest"
	"os"
	"regexp"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/alicangunduz/raggie/services/edge/internal/ports"
	"github.com/alicangunduz/raggie/services/edge/internal/ports/mock"
	"github.com/alicangunduz/raggie/services/edge/internal/rag"
	"github.com/alicangunduz/raggie/services/edge/internal/store"
	"github.com/alicangunduz/raggie/services/edge/internal/widgetauth"
)

// recordingChat records every prompt it is sent and answers "ok".
type recordingChat struct {
	mu   sync.Mutex
	seen []string
}

func (c *recordingChat) Stream(_ context.Context, req ports.ChatRequest) (<-chan ports.ChatChunk, error) {
	var b strings.Builder
	for _, m := range req.Messages {
		b.WriteString(m.Content)
		b.WriteString("\n")
	}
	c.mu.Lock()
	c.seen = append(c.seen, b.String())
	c.mu.Unlock()
	return mock.ChatProvider{Response: "ok"}.Stream(context.Background(), req)
}

func (c *recordingChat) prompts() string {
	c.mu.Lock()
	defer c.mu.Unlock()
	return strings.Join(c.seen, "\n---\n")
}

var metaConvRe = regexp.MustCompile(`"conversation_id":"([^"]+)"`)

type idorFixture struct {
	pool                  *pgxpool.Pool
	st                    *store.Store
	orgID, intWS, extWS   string
	alice, bob            string
	aliceConv, widgetConv string
}

func newIDORFixture(t *testing.T) idorFixture {
	t.Helper()
	dsn := os.Getenv("DATABASE_URL")
	if dsn == "" {
		t.Skip("DATABASE_URL not set")
	}
	ctx := context.Background()
	pool, err := pgxpool.New(ctx, dsn)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(pool.Close)
	if _, err := pool.Exec(ctx,
		"ALTER TABLE users ADD COLUMN IF NOT EXISTS is_platform_admin BOOLEAN NOT NULL DEFAULT FALSE;"+
			" ALTER TABLE messages ADD COLUMN IF NOT EXISTS interrupted_reason TEXT"); err != nil {
		t.Fatal(err)
	}
	st, err := store.New(ctx, dsn)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(st.Close)

	f := idorFixture{pool: pool, st: st}
	scan := func(sql string, args ...any) string {
		t.Helper()
		var id string
		if err := pool.QueryRow(ctx, sql, args...).Scan(&id); err != nil {
			t.Fatalf("%s: %v", sql, err)
		}
		return id
	}
	f.orgID = scan("INSERT INTO organizations(name) VALUES('idor-org') RETURNING id::text")
	// Users, workspaces, conversations and messages cascade from the org.
	t.Cleanup(func() {
		if _, err := pool.Exec(context.Background(),
			"DELETE FROM organizations WHERE id = $1::uuid", f.orgID); err != nil {
			t.Errorf("cleanup idor org: %v", err)
		}
	})
	f.intWS = scan("INSERT INTO workspaces(org_id,name,type) VALUES($1::uuid,'int','INTERNAL') RETURNING id::text", f.orgID)
	f.extWS = scan("INSERT INTO workspaces(org_id,name,type,cors_allowed_origins)"+
		" VALUES($1::uuid,'ext','EXTERNAL','[\"https://acme.example\"]'::jsonb) RETURNING id::text", f.orgID)
	user := func() string {
		id := scan("INSERT INTO users(org_id,email,password_hash,role)"+
			" VALUES($1::uuid, gen_random_uuid()::text || '@idor.test','h','STAFF') RETURNING id::text", f.orgID)
		if _, err := pool.Exec(ctx,
			"INSERT INTO workspace_members(workspace_id,user_id) VALUES($1::uuid,$2::uuid)", f.intWS, id); err != nil {
			t.Fatal(err)
		}
		return id
	}
	f.alice, f.bob = user(), user()

	if f.aliceConv, err = st.EnsureConversation(ctx, f.intWS, f.alice, ""); err != nil {
		t.Fatal(err)
	}
	if _, err := st.InsertMessage(ctx, f.aliceConv, "USER", "alice private salary question", 0, "", false); err != nil {
		t.Fatal(err)
	}
	if f.widgetConv, err = st.EnsureConversation(ctx, f.extWS, "", "victim-sid"); err != nil {
		t.Fatal(err)
	}
	if _, err := st.InsertMessage(ctx, f.widgetConv, "USER", "victim widget secret", 0, "", false); err != nil {
		t.Fatal(err)
	}
	return f
}

func (f idorFixture) messageCount(t *testing.T, conv string) int {
	t.Helper()
	var n int
	if err := f.pool.QueryRow(context.Background(),
		"SELECT count(*) FROM messages WHERE conversation_id=$1::uuid", conv).Scan(&n); err != nil {
		t.Fatal(err)
	}
	return n
}

func (f idorFixture) server(t *testing.T, chat *recordingChat) *http.Server {
	deps := Deps{
		RAG:    rag.New(mock.QueryEmbedder{Dim: 8}, mock.VectorStore{}),
		Chat:   chat,
		Store:  f.st,
		WSInfo: f.st,
	}
	cfg := widgetCfg()
	cfg.HistoryMaxMessages = 16
	return newSrvWithCfg(t, cfg, deps)
}

func metaConversationID(t *testing.T, body string) string {
	t.Helper()
	m := metaConvRe.FindStringSubmatch(body)
	if m == nil {
		t.Fatalf("no meta conversation_id in:\n%s", body)
	}
	return m[1]
}

// Bob replays Alice's conversation id: he must get a NEW conversation, must not
// see Alice's history in his prompt, and must not append to Alice's thread.
func TestChatIgnoresForeignConversationIDForInternalUser(t *testing.T) {
	f := newIDORFixture(t)
	chat := &recordingChat{}
	srv := f.server(t, chat)
	before := f.messageCount(t, f.aliceConv)

	req := httptest.NewRequest(http.MethodPost, "/api/v1/chat/stream", strings.NewReader(
		`{"workspace_id":"`+f.intWS+`","conversation_id":"`+f.aliceConv+`","message":"hello"}`))
	req.Header.Set("Authorization", "Bearer "+adminToken(t, "STAFF", f.bob))
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d (%s)", rec.Code, rec.Body.String())
	}
	if got := metaConversationID(t, rec.Body.String()); got == f.aliceConv {
		t.Fatal("bob was handed alice's conversation")
	}
	if strings.Contains(chat.prompts(), "alice private salary question") {
		t.Fatal("alice's history leaked into bob's prompt")
	}
	if after := f.messageCount(t, f.aliceConv); after != before {
		t.Fatalf("bob appended to alice's conversation (%d -> %d messages)", before, after)
	}

	// Alice herself still resumes her own conversation with its history.
	chat2 := &recordingChat{}
	srv2 := f.server(t, chat2)
	req = httptest.NewRequest(http.MethodPost, "/api/v1/chat/stream", strings.NewReader(
		`{"workspace_id":"`+f.intWS+`","conversation_id":"`+f.aliceConv+`","message":"follow-up"}`))
	req.Header.Set("Authorization", "Bearer "+adminToken(t, "STAFF", f.alice))
	rec = httptest.NewRecorder()
	srv2.Handler.ServeHTTP(rec, req)
	if got := metaConversationID(t, rec.Body.String()); got != f.aliceConv {
		t.Fatalf("owner should resume her conversation, got %s", got)
	}
	if !strings.Contains(chat2.prompts(), "alice private salary question") {
		t.Fatal("owner's history should be replayed")
	}
}

// A widget visitor replays another visitor's conversation id (the client-side
// session_token is attacker-controlled and ignored): new conversation, no leak.
func TestChatIgnoresForeignConversationIDForWidgetSession(t *testing.T) {
	f := newIDORFixture(t)
	chat := &recordingChat{}
	srv := f.server(t, chat)
	before := f.messageCount(t, f.widgetConv)

	tok, _ := widgetauth.Mint("test-secret", f.extWS, 30*time.Minute, time.Now())
	req := httptest.NewRequest(http.MethodPost, "/api/v1/chat/stream", strings.NewReader(
		`{"workspace_id":"`+f.extWS+`","conversation_id":"`+f.widgetConv+`","session_token":"victim-sid","message":"hello"}`))
	req.Header.Set("Origin", "https://acme.example")
	req.Header.Set("Authorization", "Bearer "+tok)
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d (%s)", rec.Code, rec.Body.String())
	}
	newConv := metaConversationID(t, rec.Body.String())
	if newConv == f.widgetConv {
		t.Fatal("attacker was handed the victim's widget conversation")
	}
	if strings.Contains(chat.prompts(), "victim widget secret") {
		t.Fatal("victim's widget history leaked into the attacker's prompt")
	}
	if after := f.messageCount(t, f.widgetConv); after != before {
		t.Fatalf("attacker appended to the victim's conversation (%d -> %d)", before, after)
	}

	// The same widget session (same token) can continue its OWN conversation.
	chat2 := &recordingChat{}
	srv2 := f.server(t, chat2)
	req = httptest.NewRequest(http.MethodPost, "/api/v1/chat/stream", strings.NewReader(
		`{"workspace_id":"`+f.extWS+`","conversation_id":"`+newConv+`","message":"second turn"}`))
	req.Header.Set("Origin", "https://acme.example")
	req.Header.Set("Authorization", "Bearer "+tok)
	rec = httptest.NewRecorder()
	srv2.Handler.ServeHTTP(rec, req)
	if got := metaConversationID(t, rec.Body.String()); got != newConv {
		t.Fatalf("widget session should resume its own conversation, got %s want %s", got, newConv)
	}
	if !strings.Contains(chat2.prompts(), "hello") {
		t.Fatal("own widget history should be replayed")
	}
}

// An authenticated user's stored users.locale picks the template when the
// request names none; an explicit locale field still wins.
func TestChatPromptFollowsStoredUserLocale(t *testing.T) {
	f := newIDORFixture(t)
	if _, err := f.pool.Exec(context.Background(), "UPDATE users SET locale='tr' WHERE id=$1::uuid", f.alice); err != nil {
		t.Fatal(err)
	}
	for _, tc := range []struct{ body, want string }{
		{`{"workspace_id":"` + f.intWS + `","message":"hi"}`, "Sen Raggie'sin"},
		{`{"workspace_id":"` + f.intWS + `","message":"hi","locale":"en"}`, "You are Raggie"},
	} {
		chat := &recordingChat{}
		srv := f.server(t, chat)
		req := httptest.NewRequest(http.MethodPost, "/api/v1/chat/stream", strings.NewReader(tc.body))
		req.Header.Set("Authorization", "Bearer "+adminToken(t, "STAFF", f.alice))
		rec := httptest.NewRecorder()
		srv.Handler.ServeHTTP(rec, req)
		if rec.Code != http.StatusOK || !strings.Contains(chat.prompts(), tc.want) {
			t.Fatalf("body %s: code=%d, prompt missing %q:\n%s", tc.body, rec.Code, tc.want, chat.prompts())
		}
	}
}

// Clearing your history deletes only your own conversations: every other
// user's, in the same workspace and in another org, survives.
func TestDeleteAllConversationsKeepsOtherUsersConversations(t *testing.T) {
	f := newMatrixFixture(t)
	srv := New(f.cfg, discardLogger(), f.deps)
	mine, _ := f.seedConversation(t, f.wsAInternal, f.users[pStaffMember], "mine")
	sameWS, _ := f.seedConversation(t, f.wsAInternal, f.users[pStaffNonMember], "colleague")
	otherOrg, _ := f.seedConversation(t, f.wsBExternal, f.users[pSuperOtherOrg], "other org")

	req := jsonReq(http.MethodDelete, "/api/v1/conversations", "")
	for k, v := range f.headers[pStaffMember] {
		req.Header.Set(k, v)
	}
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK || !strings.Contains(rec.Body.String(), `"deleted":1`) {
		t.Fatalf("expected 200 with deleted=1, got %d (%s)", rec.Code, rec.Body.String())
	}
	exists := func(id string) bool {
		var n int
		if err := f.pool.QueryRow(context.Background(),
			"SELECT count(*) FROM conversations WHERE id = $1::uuid", id).Scan(&n); err != nil {
			t.Fatal(err)
		}
		return n == 1
	}
	if exists(mine) {
		t.Error("the caller's own conversation was not deleted")
	}
	if !exists(sameWS) || !exists(otherOrg) {
		t.Errorf("another user's conversation was deleted (same workspace kept=%v, other org kept=%v)",
			exists(sameWS), exists(otherOrg))
	}
}
