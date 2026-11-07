// SPDX-License-Identifier: Apache-2.0

package store

import (
	"context"
	"os"
	"testing"

	"github.com/jackc/pgx/v5/pgxpool"
)

// liveStore connects to the disposable test Postgres (DATABASE_URL, which
// already carries the control-plane schema) or skips. It applies the one column
// from migration 0024 the edge depends on, idempotently, so the test does not
// depend on migration ordering in the shared test database.
func liveStore(t *testing.T) (*Store, *pgxpool.Pool) {
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
			" ALTER TABLE messages ADD COLUMN IF NOT EXISTS interrupted_reason TEXT",
	); err != nil {
		t.Fatal(err)
	}
	st, err := New(ctx, dsn)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(st.Close)
	return st, pool
}

func mustScanID(t *testing.T, pool *pgxpool.Pool, sql string, args ...any) string {
	t.Helper()
	var id string
	if err := pool.QueryRow(context.Background(), sql, args...).Scan(&id); err != nil {
		t.Fatalf("%s: %v", sql, err)
	}
	return id
}

func seedOrg(t *testing.T, pool *pgxpool.Pool, name string) (orgID, wsID string) {
	t.Helper()
	orgID = mustScanID(t, pool, "INSERT INTO organizations(name) VALUES($1) RETURNING id::text", name)
	cleanupOrg(t, pool, orgID)
	wsID = mustScanID(t, pool,
		"INSERT INTO workspaces(org_id,name,type) VALUES($1::uuid,'ws','EXTERNAL') RETURNING id::text", orgID)
	return orgID, wsID
}

// cleanupOrg deletes a seeded org when the test ends. Users, workspaces,
// memberships, conversations and messages all cascade from organizations, so
// the shared test database is left as it was found.
func cleanupOrg(t *testing.T, pool *pgxpool.Pool, orgID string) {
	t.Helper()
	t.Cleanup(func() {
		if _, err := pool.Exec(context.Background(),
			"DELETE FROM organizations WHERE id = $1::uuid", orgID); err != nil {
			t.Errorf("cleanup org %s: %v", orgID, err)
		}
	})
}

func seedUser(t *testing.T, pool *pgxpool.Pool, orgID, role string, platform, active bool) string {
	t.Helper()
	return mustScanID(t, pool,
		"INSERT INTO users(org_id,email,password_hash,role,is_platform_admin,is_active)"+
			" VALUES($1::uuid, gen_random_uuid()::text || '@access.test','h',$2,$3,$4) RETURNING id::text",
		orgID, role, platform, active)
}

// SUPER_ADMIN is org-scoped: it bypasses membership only inside its own org.
// Only users.is_platform_admin crosses orgs. Deactivated users never pass.
func TestUserCanAccessWorkspaceIsOrgScoped(t *testing.T) {
	st, pool := liveStore(t)
	ctx := context.Background()

	orgA, wsA := seedOrg(t, pool, "access-org-a")
	_, wsB := seedOrg(t, pool, "access-org-b")

	superA := seedUser(t, pool, orgA, "SUPER_ADMIN", false, true)
	platform := seedUser(t, pool, orgA, "SUPER_ADMIN", true, true)
	staffA := seedUser(t, pool, orgA, "STAFF", false, true)
	memberA := seedUser(t, pool, orgA, "STAFF", false, true)
	inactiveSuper := seedUser(t, pool, orgA, "SUPER_ADMIN", false, false)
	inactiveMember := seedUser(t, pool, orgA, "STAFF", false, false)
	for _, u := range []string{memberA, inactiveMember} {
		if _, err := pool.Exec(ctx,
			"INSERT INTO workspace_members(workspace_id,user_id) VALUES($1::uuid,$2::uuid)", wsA, u); err != nil {
			t.Fatal(err)
		}
	}

	cases := []struct {
		name      string
		user, ws  string
		wantAllow bool
	}{
		{"super admin, own org", superA, wsA, true},
		{"super admin, other org (public widget id)", superA, wsB, false},
		{"platform admin, other org", platform, wsB, true},
		{"staff non-member, own org", staffA, wsA, false},
		{"member, own workspace", memberA, wsA, true},
		{"member, other org", memberA, wsB, false},
		{"deactivated super admin", inactiveSuper, wsA, false},
		{"deactivated member", inactiveMember, wsA, false},
	}
	for _, tc := range cases {
		got, err := st.UserCanAccessWorkspace(ctx, tc.user, tc.ws)
		if err != nil {
			t.Fatalf("%s: %v", tc.name, err)
		}
		if got != tc.wantAllow {
			t.Errorf("%s: allowed=%v, want %v", tc.name, got, tc.wantAllow)
		}
	}
}

// A SUPER_ADMIN token without an org must not widen oversight to every
// workspace of every org (the old "empty org = all" branch).
func TestAdminOrgWorkspaceIDsEmptyOrgIsFailClosed(t *testing.T) {
	st, pool := liveStore(t)
	seedOrg(t, pool, "oversight-org")
	ids, err := st.AdminOrgWorkspaceIDs(context.Background(), "")
	if err != nil {
		t.Fatal(err)
	}
	if len(ids) != 0 {
		t.Fatalf("empty org must yield no workspaces, got %d", len(ids))
	}
}

// A client-supplied conversation id is honoured only when it belongs to the
// same workspace AND the same principal: the authenticated user, or the widget
// session the conversation was created under. Anything else — including ids
// that are not UUIDs — is "not owned", so the caller starts a fresh
// conversation instead of reading/appending to someone else's.
func TestOwnsConversation(t *testing.T) {
	st, pool := liveStore(t)
	ctx := context.Background()
	orgA, wsA := seedOrg(t, pool, "conv-org-a")
	_, wsB := seedOrg(t, pool, "conv-org-b")
	alice := seedUser(t, pool, orgA, "STAFF", false, true)
	bob := seedUser(t, pool, orgA, "STAFF", false, true)

	aliceConv, err := st.EnsureConversation(ctx, wsA, alice, "")
	if err != nil {
		t.Fatal(err)
	}
	widgetConv, err := st.EnsureConversation(ctx, wsA, "", "sid-victim")
	if err != nil {
		t.Fatal(err)
	}

	cases := []struct {
		name               string
		conv, ws, user, sk string
		want               bool
	}{
		{"owner user", aliceConv, wsA, alice, "", true},
		{"other user same workspace", aliceConv, wsA, bob, "", false},
		{"owner user, wrong workspace", aliceConv, wsB, alice, "", false},
		{"anonymous caller on a user conversation", aliceConv, wsA, "", "", false},
		{"widget session owner", widgetConv, wsA, "", "sid-victim", true},
		{"other widget session", widgetConv, wsA, "", "sid-attacker", false},
		{"widget session, wrong workspace", widgetConv, wsB, "", "sid-victim", false},
		{"no principal at all", widgetConv, wsA, "", "", false},
		{"user cannot claim a widget conversation", widgetConv, wsA, alice, "", false},
		{"non-uuid id", "not-a-uuid", wsA, alice, "", false},
		{"unknown id", "00000000-0000-4000-8000-000000000000", wsA, alice, "", false},
	}
	for _, tc := range cases {
		got, err := st.OwnsConversation(ctx, tc.conv, tc.ws, tc.user, tc.sk)
		if err != nil {
			t.Fatalf("%s: %v", tc.name, err)
		}
		if got != tc.want {
			t.Errorf("%s: owned=%v, want %v", tc.name, got, tc.want)
		}
	}
}

// The MCP Jira tools run on the OPERATOR's mcp-atlassian credentials, so an
// org-level integration row marked 'connected' only unlocks them when a
// platform admin created it. Rows created by org users (or with no creator)
// never do, even if their status says connected.
func TestHasConnectedJiraRequiresPlatformAdminCreator(t *testing.T) {
	st, pool := liveStore(t)
	ctx := context.Background()

	cases := []struct {
		name    string
		creator func(orgID string) any
		want    bool
	}{
		{"created by platform admin", func(org string) any { return seedUser(t, pool, org, "SUPER_ADMIN", true, true) }, true},
		{"created by org super admin", func(org string) any { return seedUser(t, pool, org, "SUPER_ADMIN", false, true) }, false},
		{"no creator recorded", func(string) any { return nil }, false},
	}
	for _, tc := range cases {
		orgID, wsID := seedOrg(t, pool, "jira-gate-org")
		if _, err := pool.Exec(ctx,
			"INSERT INTO integrations(org_id,scope_type,scope_id,provider,status,config,created_by)"+
				" VALUES($1::uuid,'org',$1::uuid,'jira','connected','{}'::jsonb,$2::uuid)",
			orgID, tc.creator(orgID)); err != nil {
			t.Fatalf("%s: seed integration: %v", tc.name, err)
		}
		got, err := st.HasConnectedJira(ctx, wsID)
		if err != nil {
			t.Fatalf("%s: %v", tc.name, err)
		}
		if got != tc.want {
			t.Errorf("%s: HasConnectedJira=%v, want %v", tc.name, got, tc.want)
		}
	}
}

// Re-rating a message updates the single (message_id, user_id) row through
// the ON CONFLICT upsert (backed by the unique index after migration 0025),
// and a thumbs-down flags the conversation. Deleting the org then cascades
// through the feedback rows.
func TestMessageFeedbackUpsert(t *testing.T) {
	st, pool := liveStore(t)
	ctx := context.Background()
	orgID, wsID := seedOrg(t, pool, "feedback-org")
	user := seedUser(t, pool, orgID, "STAFF", false, true)
	conv, err := st.EnsureConversation(ctx, wsID, user, "")
	if err != nil {
		t.Fatal(err)
	}
	msg, err := st.InsertMessage(ctx, conv, "BOT", "answer", 1, "", false)
	if err != nil {
		t.Fatal(err)
	}
	for _, rating := range []string{"up", "down"} {
		ok, err := st.InsertMessageFeedback(ctx, msg, user, rating)
		if err != nil || !ok {
			t.Fatalf("rate %s: ok=%v err=%v", rating, ok, err)
		}
	}
	var n int
	var rating string
	if err := pool.QueryRow(ctx,
		"SELECT count(*), max(rating) FROM message_feedback WHERE message_id = $1::uuid", msg,
	).Scan(&n, &rating); err != nil {
		t.Fatal(err)
	}
	var flagged bool
	if err := pool.QueryRow(ctx, "SELECT is_flagged FROM conversations WHERE id = $1::uuid", conv).Scan(&flagged); err != nil {
		t.Fatal(err)
	}
	if n != 1 || rating != "down" || !flagged {
		t.Fatalf("upsert: rows=%d rating=%q flagged=%v, want 1/down/true", n, rating, flagged)
	}
}
