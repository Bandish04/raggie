// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"context"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"slices"
	"sort"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/alicangunduz/raggie/services/edge/internal/config"
	"github.com/alicangunduz/raggie/services/edge/internal/ports/mock"
	"github.com/alicangunduz/raggie/services/edge/internal/rag"
	"github.com/alicangunduz/raggie/services/edge/internal/store"
	"github.com/alicangunduz/raggie/services/edge/internal/widgetauth"
)

// ── Authorization matrix ─────────────────────────────────────────────────────
//
// Every route registered on the edge (public mux + internal metrics listener)
// must have at least one scenario below; TestAuthzMatrixCoversEveryRoute fails
// otherwise, so a new endpoint cannot ship without an explicit policy. Each
// scenario lists the principals that are ALLOWED (2xx); every other principal
// must be DENIED with 401, 403 or 404. Scenarios run against a real Postgres
// seeded with two orgs (A = the target, B = the foreign org).

type principal string

// #nosec G101 -- principal labels, not credentials.
const (
	pAnonymous      principal = "anonymous"
	pWidgetOwn      principal = "widget_token_own_workspace"
	pWidgetOther    principal = "widget_token_other_org_workspace"
	pStaffMember    principal = "staff_member"
	pStaffNonMember principal = "staff_non_member"
	pSuperSameOrg   principal = "super_admin_same_org"
	pSuperOtherOrg  principal = "super_admin_other_org"
	pPlatformAdmin  principal = "platform_admin"
	pDeactivated    principal = "deactivated_user"
	pRevoked        principal = "revoked_session"
	pInternalSecret principal = "internal_secret"
)

var allPrincipals = []principal{
	pAnonymous, pWidgetOwn, pWidgetOther, pStaffMember, pStaffNonMember,
	pSuperSameOrg, pSuperOtherOrg, pPlatformAdmin, pDeactivated, pRevoked, pInternalSecret,
}

// authenticatedActive are the principals holding a valid admin-audience token
// for an active user with a live session.
var authenticatedActive = []principal{
	pStaffMember, pStaffNonMember, pSuperSameOrg, pSuperOtherOrg, pPlatformAdmin,
}

// #nosec G101 -- throwaway test secrets for the in-process fixture.
const (
	matrixJWTSecret      = "matrix-jwt-secret-0123456789abcdef0123"
	matrixWidgetSecret   = "matrix-widget-secret-0123456789abcdef01"
	matrixInternalSecret = "matrix-internal-secret-0123456789abcdef"
	matrixMetricsToken   = "matrix-metrics-token-0123456789abcdef01"
	matrixOrigin         = "https://acme.example"
)

type authzScenario struct {
	route   string // exact registered pattern, e.g. "GET /api/v1/conversations"
	name    string
	allowed []principal
	// build returns a fresh request (it may seed per-request resources).
	build func(t *testing.T, f *matrixFixture) *http.Request
	// check optionally inspects an ALLOWED response (e.g. no cross-org data).
	check func(t *testing.T, f *matrixFixture, p principal, rec *httptest.ResponseRecorder)
	// metrics routes are served by the internal metrics listener.
	metrics bool
}

func jsonReq(method, path, body string) *http.Request {
	var r *http.Request
	if body == "" {
		r = httptest.NewRequest(method, path, nil)
	} else {
		r = httptest.NewRequest(method, path, strings.NewReader(body))
		r.Header.Set("Content-Type", "application/json")
	}
	return r
}

func authzScenarios() []authzScenario {
	everyone := allPrincipals
	return []authzScenario{
		{route: "GET /healthz", name: "public liveness", allowed: everyone,
			build: func(*testing.T, *matrixFixture) *http.Request { return jsonReq(http.MethodGet, "/healthz", "") }},
		{route: "GET /readyz", name: "public readiness", allowed: everyone,
			build: func(*testing.T, *matrixFixture) *http.Request { return jsonReq(http.MethodGet, "/readyz", "") }},

		{route: "POST /api/v1/chat/stream", name: "internal workspace of org A",
			allowed: []principal{pStaffMember, pSuperSameOrg, pPlatformAdmin},
			build: func(_ *testing.T, f *matrixFixture) *http.Request {
				return jsonReq(http.MethodPost, "/api/v1/chat/stream",
					`{"workspace_id":"`+f.wsAInternal+`","message":"hi"}`)
			}},
		{route: "POST /api/v1/chat/stream", name: "external widget workspace of org A",
			allowed: []principal{pWidgetOwn},
			build: func(_ *testing.T, f *matrixFixture) *http.Request {
				r := jsonReq(http.MethodPost, "/api/v1/chat/stream",
					`{"workspace_id":"`+f.wsAExternal+`","message":"hi"}`)
				r.Header.Set("Origin", matrixOrigin)
				return r
			}},
		{route: "POST /api/v1/chat/stream", name: "all-workspaces set reaching org B's widget workspace",
			allowed: []principal{pPlatformAdmin},
			build: func(_ *testing.T, f *matrixFixture) *http.Request {
				return jsonReq(http.MethodPost, "/api/v1/chat/stream",
					`{"workspace_id":"`+f.wsAInternal+`","workspace_ids":["`+f.wsAInternal+`","`+f.wsBExternal+`"],"message":"hi"}`)
			}},

		{route: "POST /api/v1/skills/generate-instructions", name: "any active internal user",
			allowed: authenticatedActive,
			build: func(*testing.T, *matrixFixture) *http.Request {
				return jsonReq(http.MethodPost, "/api/v1/skills/generate-instructions", `{"description":"hr helper"}`)
			}},

		{route: "POST /api/v1/internal/run-task", name: "server-to-server, owner still a member",
			allowed: []principal{pInternalSecret},
			build: func(_ *testing.T, f *matrixFixture) *http.Request {
				return jsonReq(http.MethodPost, "/api/v1/internal/run-task",
					`{"workspace_id":"`+f.wsAInternal+`","user_id":"`+f.users[pStaffMember]+`","prompt":"report"}`)
			}},
		{route: "POST /api/v1/internal/run-task", name: "owner deactivated since scheduling",
			allowed: nil,
			build: func(_ *testing.T, f *matrixFixture) *http.Request {
				return jsonReq(http.MethodPost, "/api/v1/internal/run-task",
					`{"workspace_id":"`+f.wsAInternal+`","user_id":"`+f.users[pDeactivated]+`","prompt":"report"}`)
			}},

		{route: "POST /api/v1/schedule/parse", name: "any active internal user",
			allowed: authenticatedActive,
			build: func(*testing.T, *matrixFixture) *http.Request {
				return jsonReq(http.MethodPost, "/api/v1/schedule/parse", `{"text":"every morning at 9"}`)
			}},

		{route: "GET /api/v1/models", name: "any active internal user",
			allowed: authenticatedActive,
			build:   func(*testing.T, *matrixFixture) *http.Request { return jsonReq(http.MethodGet, "/api/v1/models", "") }},

		{route: "GET /api/v1/conversations", name: "own history only",
			allowed: authenticatedActive,
			build: func(t *testing.T, f *matrixFixture) *http.Request {
				f.seedConversation(t, f.wsAInternal, f.users[pStaffMember], "staff private question")
				return jsonReq(http.MethodGet, "/api/v1/conversations", "")
			},
			check: func(t *testing.T, _ *matrixFixture, p principal, rec *httptest.ResponseRecorder) {
				if p != pStaffMember && strings.Contains(rec.Body.String(), "staff private question") {
					t.Errorf("%s sees another user's conversation list", p)
				}
			}},
		{route: "GET /api/v1/conversations/{id}/messages", name: "owner only",
			allowed: []principal{pStaffMember},
			build: func(t *testing.T, f *matrixFixture) *http.Request {
				conv, _ := f.seedConversation(t, f.wsAInternal, f.users[pStaffMember], "staff private question")
				return jsonReq(http.MethodGet, "/api/v1/conversations/"+conv+"/messages", "")
			},
			check: func(t *testing.T, _ *matrixFixture, _ principal, rec *httptest.ResponseRecorder) {
				if !strings.Contains(rec.Body.String(), "staff private question") {
					t.Errorf("owner did not get her messages: %s", rec.Body.String())
				}
			}},
		{route: "DELETE /api/v1/conversations/{id}", name: "owner only",
			allowed: []principal{pStaffMember},
			build: func(t *testing.T, f *matrixFixture) *http.Request {
				conv, _ := f.seedConversation(t, f.wsAInternal, f.users[pStaffMember], "to delete")
				return jsonReq(http.MethodDelete, "/api/v1/conversations/"+conv, "")
			}},
		{route: "DELETE /api/v1/conversations", name: "clears only the caller's own history",
			allowed: authenticatedActive,
			build: func(*testing.T, *matrixFixture) *http.Request {
				return jsonReq(http.MethodDelete, "/api/v1/conversations", "")
			}},
		{route: "POST /api/v1/messages/{id}/feedback", name: "conversation owner only",
			allowed: []principal{pStaffMember},
			build: func(t *testing.T, f *matrixFixture) *http.Request {
				_, botMsg := f.seedConversation(t, f.wsAInternal, f.users[pStaffMember], "rate me")
				return jsonReq(http.MethodPost, "/api/v1/messages/"+botMsg+"/feedback", `{"rating":"up"}`)
			}},

		{route: "GET /api/v1/admin/conversations", name: "filtered to org A's workspace",
			allowed: []principal{pSuperSameOrg, pPlatformAdmin},
			build: func(t *testing.T, f *matrixFixture) *http.Request {
				f.seedConversation(t, f.wsAInternal, f.users[pStaffMember], "oversight question")
				return jsonReq(http.MethodGet, "/api/v1/admin/conversations?workspace_id="+f.wsAInternal, "")
			}},
		{route: "GET /api/v1/admin/conversations", name: "default scope never crosses orgs",
			allowed: []principal{pSuperSameOrg, pSuperOtherOrg, pPlatformAdmin},
			build: func(t *testing.T, f *matrixFixture) *http.Request {
				f.seedConversation(t, f.wsAInternal, f.users[pStaffMember], "org A oversight secret")
				return jsonReq(http.MethodGet, "/api/v1/admin/conversations", "")
			},
			check: func(t *testing.T, _ *matrixFixture, p principal, rec *httptest.ResponseRecorder) {
				leaked := strings.Contains(rec.Body.String(), "org A oversight secret")
				if p == pSuperSameOrg && !leaked {
					t.Errorf("org A super admin should see org A conversations")
				}
				if p != pSuperSameOrg && leaked {
					t.Errorf("%s's default oversight scope leaked org A conversations", p)
				}
			}},
		{route: "GET /api/v1/admin/conversations/{id}/messages", name: "conversation in org A",
			allowed: []principal{pSuperSameOrg, pPlatformAdmin},
			build: func(t *testing.T, f *matrixFixture) *http.Request {
				conv, _ := f.seedConversation(t, f.wsAInternal, f.users[pStaffMember], "oversight thread")
				return jsonReq(http.MethodGet, "/api/v1/admin/conversations/"+conv+"/messages", "")
			}},
		{route: "GET /api/v1/admin/mcp/capabilities", name: "admins only",
			allowed: []principal{pSuperSameOrg, pSuperOtherOrg, pPlatformAdmin},
			build: func(*testing.T, *matrixFixture) *http.Request {
				return jsonReq(http.MethodGet, "/api/v1/admin/mcp/capabilities", "")
			}},

		{route: "POST /api/v1/widget/token", name: "public issuance for org A's widget workspace",
			allowed: everyone,
			build: func(_ *testing.T, f *matrixFixture) *http.Request {
				r := jsonReq(http.MethodPost, "/api/v1/widget/token", `{"workspace_id":"`+f.wsAExternal+`"}`)
				r.Header.Set("Origin", matrixOrigin)
				return r
			}},
		{route: "POST /api/v1/widget/token", name: "never for an INTERNAL workspace",
			allowed: nil,
			build: func(_ *testing.T, f *matrixFixture) *http.Request {
				r := jsonReq(http.MethodPost, "/api/v1/widget/token", `{"workspace_id":"`+f.wsAInternal+`"}`)
				r.Header.Set("Origin", matrixOrigin)
				return r
			}},
		{route: "OPTIONS /api/v1/widget/token", name: "public CORS preflight", allowed: everyone,
			build: func(*testing.T, *matrixFixture) *http.Request {
				r := jsonReq(http.MethodOptions, "/api/v1/widget/token", "")
				r.Header.Set("Origin", matrixOrigin)
				return r
			}},
		{route: "OPTIONS /api/v1/chat/stream", name: "public CORS preflight for widget chat", allowed: everyone,
			build: func(*testing.T, *matrixFixture) *http.Request {
				r := jsonReq(http.MethodOptions, "/api/v1/chat/stream", "")
				r.Header.Set("Origin", matrixOrigin)
				return r
			}},
		{route: "GET /widgets/", name: "public widget bundle", allowed: everyone,
			build: func(*testing.T, *matrixFixture) *http.Request {
				return jsonReq(http.MethodGet, "/widgets/embed.js", "")
			}},

		{route: "GET /metrics", name: "internal listener requires the metrics token", allowed: nil, metrics: true,
			build: func(*testing.T, *matrixFixture) *http.Request { return jsonReq(http.MethodGet, "/metrics", "") }},
	}
}

// ── Fixture ──────────────────────────────────────────────────────────────────

type matrixFixture struct {
	pool *pgxpool.Pool
	st   *store.Store
	cfg  config.Config
	deps Deps

	orgA, orgB                            string
	wsAInternal, wsAExternal, wsBExternal string
	users                                 map[principal]string // principal -> user id
	headers                               map[principal]map[string]string
}

func (f *matrixFixture) scan(t *testing.T, sql string, args ...any) string {
	t.Helper()
	var id string
	if err := f.pool.QueryRow(context.Background(), sql, args...).Scan(&id); err != nil {
		t.Fatalf("%s: %v", sql, err)
	}
	return id
}

// seedConversation creates a conversation with one USER and one BOT turn and
// returns (conversation id, BOT message id).
func (f *matrixFixture) seedConversation(t *testing.T, ws, user, text string) (string, string) {
	t.Helper()
	ctx := context.Background()
	conv, err := f.st.EnsureConversation(ctx, ws, user, "")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := f.st.InsertMessage(ctx, conv, "USER", text, 0, "", false); err != nil {
		t.Fatal(err)
	}
	bot, err := f.st.InsertMessage(ctx, conv, "BOT", "answer", 1, "", false)
	if err != nil {
		t.Fatal(err)
	}
	return conv, bot
}

func newMatrixFixture(t *testing.T) *matrixFixture {
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

	f := &matrixFixture{pool: pool, st: st, users: map[principal]string{}, headers: map[principal]map[string]string{}}
	for _, name := range []string{"authz-matrix-org-a", "authz-matrix-org-b"} {
		id := f.scan(t, "INSERT INTO organizations(name) VALUES($1) RETURNING id::text", name)
		// Users, workspaces, sessions, memberships and conversations cascade.
		t.Cleanup(func() {
			if _, err := pool.Exec(context.Background(), "DELETE FROM organizations WHERE id = $1::uuid", id); err != nil {
				t.Errorf("cleanup org: %v", err)
			}
		})
		if f.orgA == "" {
			f.orgA = id
		} else {
			f.orgB = id
		}
	}
	cors := `["` + matrixOrigin + `"]`
	f.wsAInternal = f.scan(t, "INSERT INTO workspaces(org_id,name,type) VALUES($1::uuid,'a-int','INTERNAL') RETURNING id::text", f.orgA)
	f.wsAExternal = f.scan(t, "INSERT INTO workspaces(org_id,name,type,cors_allowed_origins) VALUES($1::uuid,'a-ext','EXTERNAL',$2::jsonb) RETURNING id::text", f.orgA, cors)
	f.wsBExternal = f.scan(t, "INSERT INTO workspaces(org_id,name,type,cors_allowed_origins) VALUES($1::uuid,'b-ext','EXTERNAL',$2::jsonb) RETURNING id::text", f.orgB, cors)

	type spec struct {
		p              principal
		org, role      string
		platform       bool
		active, member bool
		revoked        bool
	}
	for _, s := range []spec{
		{pStaffMember, f.orgA, "STAFF", false, true, true, false},
		{pStaffNonMember, f.orgA, "STAFF", false, true, false, false},
		{pSuperSameOrg, f.orgA, "SUPER_ADMIN", false, true, false, false},
		{pSuperOtherOrg, f.orgB, "SUPER_ADMIN", false, true, false, false},
		{pPlatformAdmin, f.orgB, "SUPER_ADMIN", true, true, false, false},
		{pDeactivated, f.orgA, "STAFF", false, false, true, false},
		{pRevoked, f.orgA, "STAFF", false, true, true, true},
	} {
		uid := f.scan(t, "INSERT INTO users(org_id,email,password_hash,role,is_platform_admin,is_active)"+
			" VALUES($1::uuid, gen_random_uuid()::text || '@matrix.test','h',$2,$3,$4) RETURNING id::text",
			s.org, s.role, s.platform, s.active)
		f.users[s.p] = uid
		if s.member {
			if _, err := pool.Exec(ctx, "INSERT INTO workspace_members(workspace_id,user_id) VALUES($1::uuid,$2::uuid)",
				f.wsAInternal, uid); err != nil {
				t.Fatal(err)
			}
		}
		var revokedAt any
		if s.revoked {
			revokedAt = time.Now().Add(-time.Minute)
		}
		sid := f.scan(t, "INSERT INTO auth_sessions(id,user_id,refresh_token_hash,expires_at,revoked_at)"+
			" VALUES(gen_random_uuid(),$1::uuid,gen_random_uuid()::text,now()+interval '1 hour',$2) RETURNING id::text", uid, revokedAt)
		tok, err := widgetauth.SignHS256(matrixJWTSecret, map[string]any{
			"aud": "admin", "type": "access", "sub": uid, "role": s.role, "org_id": s.org, "sid": sid,
			"exp": time.Now().Add(time.Hour).Unix(),
		})
		if err != nil {
			t.Fatal(err)
		}
		f.headers[s.p] = map[string]string{"Authorization": "Bearer " + tok}
	}
	own, _ := widgetauth.Mint(matrixWidgetSecret, f.wsAExternal, 30*time.Minute, time.Now())
	other, _ := widgetauth.Mint(matrixWidgetSecret, f.wsBExternal, 30*time.Minute, time.Now())
	f.headers[pWidgetOwn] = map[string]string{"Authorization": "Bearer " + own}
	f.headers[pWidgetOther] = map[string]string{"Authorization": "Bearer " + other}
	f.headers[pInternalSecret] = map[string]string{"X-Internal-Secret": matrixInternalSecret}
	f.headers[pAnonymous] = map[string]string{}

	staticDir := t.TempDir()
	if err := os.WriteFile(filepath.Join(staticDir, "embed.js"), []byte("/* widget */"), 0o600); err != nil {
		t.Fatal(err)
	}
	f.cfg = config.Config{
		Port: "8080", LogLevel: "error", Env: "test",
		JWTSecret: matrixJWTSecret, WidgetTokenSecret: matrixWidgetSecret, WidgetTokenTTLSeconds: 1800,
		InternalAPISecret: matrixInternalSecret, MetricsToken: matrixMetricsToken, MetricsAddr: "127.0.0.1:0",
		WidgetStaticDir: staticDir, ChatModel: "matrix-model", HistoryMaxMessages: 8,
		RetrieveCandidateK: 4, RetrieveContextK: 2,
	}
	f.deps = Deps{
		RAG: rag.New(mock.QueryEmbedder{Dim: 8}, mock.VectorStore{}),
		// Valid for every one-shot consumer (skills, schedule parse) and chat.
		Chat:       mock.ChatProvider{Response: `{"cron":"0 9 * * *","prompt":"report","name":"n","summary":"s"}`},
		Store:      st,
		WSInfo:     st,
		TokenState: st,
		MCP:        &fakeToolProvider{},
	}
	return f
}

// ── Tests ────────────────────────────────────────────────────────────────────

func registeredRoutes(t *testing.T) []string {
	t.Helper()
	cfg := config.Config{WidgetStaticDir: t.TempDir()} // register the conditional /widgets/ route too
	var out []string
	for _, rt := range routes(cfg, discardLogger(), Deps{}) {
		out = append(out, rt.pattern)
	}
	for _, rt := range metricsRoutes(cfg, Deps{}) {
		out = append(out, rt.pattern)
	}
	return out
}

// A route without a policy entry (or a policy for a route that no longer
// exists) fails the build: authorization must be decided explicitly.
func TestAuthzMatrixCoversEveryRoute(t *testing.T) {
	registered := registeredRoutes(t)
	covered := map[string]bool{}
	for _, sc := range authzScenarios() {
		covered[sc.route] = true
		if !slices.Contains(registered, sc.route) {
			t.Errorf("policy references unregistered route %q", sc.route)
		}
	}
	var missing []string
	for _, r := range registered {
		if !covered[r] {
			missing = append(missing, r)
		}
	}
	sort.Strings(missing)
	if len(missing) > 0 {
		t.Fatalf("routes with no authz policy entry (add scenarios to authzScenarios): %v", missing)
	}
	t.Logf("authz matrix covers %d routes", len(registered))
}

func TestAuthzMatrix(t *testing.T) {
	f := newMatrixFixture(t)
	public := New(f.cfg, discardLogger(), f.deps)
	metrics := NewMetricsServer(f.cfg, discardLogger(), f.deps)

	for _, sc := range authzScenarios() {
		for _, p := range allPrincipals {
			t.Run(sc.route+" | "+sc.name+" | "+string(p), func(t *testing.T) {
				req := sc.build(t, f)
				for k, v := range f.headers[p] {
					req.Header.Set(k, v)
				}
				srv := public
				if sc.metrics {
					srv = metrics
				}
				rec := httptest.NewRecorder()
				srv.Handler.ServeHTTP(rec, req)

				if slices.Contains(sc.allowed, p) {
					if rec.Code < 200 || rec.Code > 299 {
						t.Fatalf("expected ALLOW (2xx), got %d: %s", rec.Code, truncBody(rec))
					}
					if sc.check != nil {
						sc.check(t, f, p, rec)
					}
					return
				}
				switch rec.Code {
				case http.StatusUnauthorized, http.StatusForbidden, http.StatusNotFound:
				default:
					t.Fatalf("expected DENY (401/403/404), got %d: %s", rec.Code, truncBody(rec))
				}
			})
		}
	}
}

func truncBody(rec *httptest.ResponseRecorder) string {
	b := rec.Body.String()
	if len(b) > 300 {
		b = b[:300] + "…"
	}
	return b
}

// Malformed path ids are "not found", never a database error.
func TestConversationRoutesRejectMalformedIDs(t *testing.T) {
	f := newMatrixFixture(t)
	srv := New(f.cfg, discardLogger(), f.deps)
	for _, tc := range []struct{ method, path, body string }{
		{http.MethodGet, "/api/v1/conversations/not-a-uuid/messages", ""},
		{http.MethodDelete, "/api/v1/conversations/not-a-uuid", ""},
		{http.MethodPost, "/api/v1/messages/not-a-uuid/feedback", `{"rating":"up"}`},
		{http.MethodGet, "/api/v1/admin/conversations/not-a-uuid/messages", ""},
	} {
		req := jsonReq(tc.method, tc.path, tc.body)
		as := pStaffMember
		if strings.Contains(tc.path, "/admin/") {
			as = pSuperSameOrg
		}
		for k, v := range f.headers[as] {
			req.Header.Set(k, v)
		}
		rec := httptest.NewRecorder()
		srv.Handler.ServeHTTP(rec, req)
		if rec.Code != http.StatusNotFound {
			t.Errorf("%s %s: expected 404, got %d", tc.method, tc.path, rec.Code)
		}
	}
}
