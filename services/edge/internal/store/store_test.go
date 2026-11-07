// SPDX-License-Identifier: Apache-2.0

package store

import (
	"context"
	"errors"
	"os"
	"reflect"
	"strings"
	"testing"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

func TestDecodeStringListJSON(t *testing.T) {
	t.Parallel()

	for name, tc := range map[string]struct {
		raw  string
		want []string
	}{
		"array":  {raw: `["local","managed"]`, want: []string{"local", "managed"}},
		"legacy": {raw: `"[\"local\",\"managed\"]"`, want: []string{"local", "managed"}},
		"empty":  {raw: `[]`, want: []string{}},
	} {
		t.Run(name, func(t *testing.T) {
			got, err := decodeStringListJSON(tc.raw)
			if err != nil {
				t.Fatal(err)
			}
			if !reflect.DeepEqual(got, tc.want) {
				t.Fatalf("decodeStringListJSON(%q) = %#v, want %#v", tc.raw, got, tc.want)
			}
		})
	}
}

func TestDecodeStringListJSONRejectsWrongShape(t *testing.T) {
	t.Parallel()

	for _, raw := range []string{`{}`, `"local"`, `[1]`, `not-json`} {
		if _, err := decodeStringListJSON(raw); err == nil {
			t.Fatalf("decodeStringListJSON(%q) succeeded, want error", raw)
		}
	}
}

func TestEncodeToolCalls(t *testing.T) {
	t.Parallel()

	raw, err := encodeToolCalls([]ToolCallAudit{{
		ID: "call-1", Name: "jira_search", Kind: "mcp", OK: true, LatencyMS: 12,
		ArgsSHA256: "abc", ResultChars: 42,
	}})
	if err != nil {
		t.Fatal(err)
	}
	if raw == "" || !strings.Contains(raw, `"args_sha256":"abc"`) || strings.Contains(raw, "arguments") {
		t.Fatalf("unexpected redacted tool audit json: %s", raw)
	}
	empty, err := encodeToolCalls(nil)
	if err != nil || empty != "" {
		t.Fatalf("empty encode = %q, %v", empty, err)
	}
}

// Live Postgres test; skipped unless DATABASE_URL is set (locally it points at
// the disposable PG which already has the schema).
func TestConversationAndMessagePersistence(t *testing.T) {
	dsn := os.Getenv("DATABASE_URL")
	if dsn == "" {
		t.Skip("DATABASE_URL not set")
	}
	ctx := context.Background()
	pool, err := pgxpool.New(ctx, dsn)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(pool.Close) // after cleanupOrg (t.Cleanup is LIFO)

	var orgID, wsID string
	if err := pool.QueryRow(ctx,
		"INSERT INTO organizations(name) VALUES('edge-test') RETURNING id::text").Scan(&orgID); err != nil {
		t.Fatal(err)
	}
	cleanupOrg(t, pool, orgID)
	if err := pool.QueryRow(ctx,
		"INSERT INTO workspaces(org_id,name,type) VALUES($1::uuid,'ws','INTERNAL') RETURNING id::text",
		orgID).Scan(&wsID); err != nil {
		t.Fatal(err)
	}

	st, err := New(ctx, dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer st.Close()

	convID, err := st.EnsureConversation(ctx, wsID, "", "sess-1")
	if err != nil || convID == "" {
		t.Fatalf("EnsureConversation: id=%q err=%v", convID, err)
	}
	if _, err := st.InsertMessage(ctx, convID, "USER", "hello", 0, "", false); err != nil {
		t.Fatal(err)
	}
	botID, err := st.InsertMessageWithAudit(
		ctx,
		convID,
		"BOT",
		"hi there",
		7,
		`[{"doc":"a.txt","text":"x","score":0.9}]`,
		false,
		MessageAudit{ModelUsed: "local-general", ProviderUsed: "ollama"},
	)
	if err != nil || botID == "" {
		t.Fatalf("InsertMessage BOT: id=%q err=%v", botID, err)
	}

	var n int
	if err := pool.QueryRow(ctx,
		"SELECT count(*) FROM messages WHERE conversation_id=$1::uuid", convID).Scan(&n); err != nil {
		t.Fatal(err)
	}
	if n != 2 {
		t.Fatalf("expected 2 persisted messages, got %d", n)
	}

	// sources_json must be valid jsonb (the ::jsonb cast would have failed otherwise).
	var src []byte
	if err := pool.QueryRow(ctx,
		"SELECT sources_json FROM messages WHERE id=$1::uuid", botID).Scan(&src); err != nil {
		t.Fatal(err)
	}
	if len(src) == 0 {
		t.Fatal("expected sources_json to be stored")
	}
	var model, provider string
	if err := pool.QueryRow(ctx,
		"SELECT model_used, model_provider FROM messages WHERE id=$1::uuid",
		botID,
	).Scan(&model, &provider); err != nil {
		t.Fatal(err)
	}
	if model != "local-general" || provider != "ollama" {
		t.Fatalf("unexpected model/provider audit: %q/%q", model, provider)
	}
}

func TestResolveChatPolicyRequiresCurrentSkillVersion(t *testing.T) {
	dsn := os.Getenv("DATABASE_URL")
	if dsn == "" {
		t.Skip("DATABASE_URL not set")
	}
	ctx := context.Background()
	pool, err := pgxpool.New(ctx, dsn)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(pool.Close) // after cleanupOrg (t.Cleanup is LIFO)

	var orgID, wsID, userID, skillID string
	if err := pool.QueryRow(ctx,
		"INSERT INTO organizations(name) VALUES('skill-policy-test') RETURNING id::text",
	).Scan(&orgID); err != nil {
		t.Fatal(err)
	}
	cleanupOrg(t, pool, orgID)
	if err := pool.QueryRow(ctx,
		"INSERT INTO workspaces(org_id,name,type,system_prompt,temperature)"+
			" VALUES($1::uuid,'ws','INTERNAL','trusted workspace',0.2) RETURNING id::text",
		orgID,
	).Scan(&wsID); err != nil {
		t.Fatal(err)
	}
	if err := pool.QueryRow(ctx,
		"INSERT INTO users(org_id,email,password_hash,role)"+
			" VALUES($1::uuid,$2,'h','STAFF') RETURNING id::text",
		orgID,
		"skill-policy-"+wsID+"@example.test",
	).Scan(&userID); err != nil {
		t.Fatal(err)
	}
	if err := pool.QueryRow(ctx,
		"INSERT INTO skills(org_id,created_by,name,slug,instructions,allowed_tools)"+
			" VALUES($1::uuid,$2::uuid,'Analyst',$3,'v1',ARRAY['web_search'])"+
			" RETURNING id::text",
		orgID,
		userID,
		"analyst-"+wsID[:8],
	).Scan(&skillID); err != nil {
		t.Fatal(err)
	}

	st, err := New(ctx, dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer st.Close()

	policy, err := st.ResolveChatPolicy(ctx, userID, wsID, skillID, 1)
	if err != nil || policy.Skill == nil || policy.Skill.Version != 1 {
		t.Fatalf("resolve v1: policy=%+v err=%v", policy, err)
	}

	if _, err := pool.Exec(ctx,
		"UPDATE skills SET instructions='v2', updated_by=$2::uuid WHERE id=$1::uuid",
		skillID,
		userID,
	); err != nil {
		t.Fatal(err)
	}
	if _, err := st.ResolveChatPolicy(ctx, userID, wsID, skillID, 1); !errors.Is(err, pgx.ErrNoRows) {
		t.Fatalf("expected stale version to be rejected, got %v", err)
	}
	policy, err = st.ResolveChatPolicy(ctx, userID, wsID, skillID, 2)
	if err != nil || policy.Skill == nil || policy.Skill.Instructions != "v2" {
		t.Fatalf("resolve v2: policy=%+v err=%v", policy, err)
	}
}
