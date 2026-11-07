// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

// perWorkspaceWS grants access per workspace id and reports a type per id
// (default INTERNAL), modelling workspaces from different orgs.
type perWorkspaceWS struct {
	types  map[string]string
	access map[string]bool
}

func (f perWorkspaceWS) WorkspaceWidget(_ context.Context, id string) (string, []string, string, string, error) {
	typ, ok := f.types[id]
	if !ok {
		return "", nil, "", "", errors.New("not found")
	}
	return typ, nil, "", "", nil
}

func (f perWorkspaceWS) UserCanAccessWorkspace(_ context.Context, _, ws string) (bool, error) {
	return f.access[ws], nil
}

func TestInternalChatChecksEveryRequestedWorkspace(t *testing.T) {
	ws := perWorkspaceWS{
		types:  map[string]string{"own": "INTERNAL", "foreign": "INTERNAL", "widget": "EXTERNAL"},
		access: map[string]bool{"own": true},
	}
	cases := map[string]struct {
		body string
		want int
	}{
		"own workspace only": {`{"workspace_id":"own","message":"hi"}`, http.StatusOK},
		"foreign workspace in the all-workspaces set": {
			`{"workspace_id":"own","workspace_ids":["own","foreign"],"message":"hi"}`, http.StatusNotFound},
		"foreign EXTERNAL widget workspace in the set": {
			`{"workspace_id":"own","workspace_ids":["widget"],"message":"hi"}`, http.StatusNotFound},
		// The primary workspace (conversation owner, policy source) must be
		// authorized even when it is absent from workspace_ids.
		"foreign primary workspace with an allowed set": {
			`{"workspace_id":"foreign","workspace_ids":["own"],"message":"hi"}`, http.StatusNotFound},
	}
	for name, tc := range cases {
		t.Run(name, func(t *testing.T) {
			deps := mockDeps()
			deps.WSInfo = ws
			srv := newSrv(t, deps)
			req := httptest.NewRequest(http.MethodPost, "/api/v1/chat/stream", strings.NewReader(tc.body))
			req.Header.Set("Authorization", "Bearer "+adminToken(t, "SUPER_ADMIN", "su"))
			rec := httptest.NewRecorder()
			srv.Handler.ServeHTTP(rec, req)
			if rec.Code != tc.want {
				t.Fatalf("expected %d, got %d (%s)", tc.want, rec.Code, rec.Body.String())
			}
		})
	}
}

// A workspace the caller may not use answers exactly like one that does not
// exist (404, same body), so workspace ids from another org cannot be probed.
func TestInternalChatForeignWorkspaceLooksLikeUnknownOne(t *testing.T) {
	ws := perWorkspaceWS{types: map[string]string{"own": "INTERNAL", "foreign": "INTERNAL"},
		access: map[string]bool{"own": true}}
	deps := mockDeps()
	deps.WSInfo = ws
	srv := newSrv(t, deps)
	answer := func(body string) *httptest.ResponseRecorder {
		req := httptest.NewRequest(http.MethodPost, "/api/v1/chat/stream", strings.NewReader(body))
		req.Header.Set("Authorization", "Bearer "+adminToken(t, "SUPER_ADMIN", "su"))
		rec := httptest.NewRecorder()
		srv.Handler.ServeHTTP(rec, req)
		return rec
	}
	for name, body := range map[string]string{
		"primary": `{"workspace_id":"%s","message":"hi"}`,
		"in set":  `{"workspace_id":"own","workspace_ids":["own","%s"],"message":"hi"}`,
	} {
		foreign := answer(strings.Replace(body, "%s", "foreign", 1))
		unknown := answer(strings.Replace(body, "%s", "missing", 1))
		if foreign.Code != http.StatusNotFound || foreign.Code != unknown.Code ||
			foreign.Body.String() != unknown.Body.String() {
			t.Fatalf("%s: foreign %d %s vs unknown %d %s", name,
				foreign.Code, foreign.Body.String(), unknown.Code, unknown.Body.String())
		}
	}
}

// Admin oversight: another org's conversation or workspace answers like an
// unknown one (404, same body). Runs against Postgres (skipped without
// DATABASE_URL).
func TestAdminOversightForeignResourcesLookUnknown(t *testing.T) {
	f := newMatrixFixture(t)
	srv := New(f.cfg, discardLogger(), f.deps)
	conv, _ := f.seedConversation(t, f.wsAInternal, f.users[pStaffMember], "org A thread")
	const unknownID = "00000000-0000-4000-8000-000000000000"
	get := func(path string) *httptest.ResponseRecorder {
		req := jsonReq(http.MethodGet, path, "")
		for k, v := range f.headers[pSuperOtherOrg] {
			req.Header.Set(k, v)
		}
		rec := httptest.NewRecorder()
		srv.Handler.ServeHTTP(rec, req)
		return rec
	}
	for name, paths := range map[string][2]string{
		"conversation thread": {
			"/api/v1/admin/conversations/" + conv + "/messages",
			"/api/v1/admin/conversations/" + unknownID + "/messages",
		},
		"workspace filter": {
			"/api/v1/admin/conversations?workspace_id=" + f.wsAInternal,
			"/api/v1/admin/conversations?workspace_id=" + unknownID,
		},
	} {
		foreign, unknown := get(paths[0]), get(paths[1])
		if foreign.Code != http.StatusNotFound || foreign.Code != unknown.Code ||
			foreign.Body.String() != unknown.Body.String() {
			t.Errorf("%s: foreign %d %s vs unknown %d %s", name,
				foreign.Code, foreign.Body.String(), unknown.Code, unknown.Body.String())
		}
	}
}
