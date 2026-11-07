// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"log/slog"
	"net/http"
	"slices"
	"strconv"

	"github.com/alicangunduz/raggie/services/edge/internal/config"
	"github.com/alicangunduz/raggie/services/edge/internal/store"
)

// adminPrincipal is the authorization view of an admin caller.
type adminPrincipal struct {
	userID string
	store.AdminPrincipal
}

// adminClaims verifies an aud=admin access token and resolves the caller's
// role, org and platform-admin flag. With a database these come from the users
// row (authoritative: a demotion or deactivation applies immediately); only the
// no-DB mode falls back to the token claims. On failure it writes 401.
func adminClaims(cfg config.Config, deps Deps, w http.ResponseWriter, r *http.Request) (adminPrincipal, bool) {
	claims, verified := verifiedAdminClaims(cfg, deps, r)
	userID, _ := claims["sub"].(string)
	if !verified || userID == "" {
		writeError(w, r, http.StatusUnauthorized, errCodeUnauth)
		return adminPrincipal{}, false
	}
	p := adminPrincipal{userID: userID}
	if deps.Store == nil {
		p.Role, _ = claims["role"].(string)
		p.OrgID, _ = claims["org_id"].(string)
		return p, true
	}
	dbp, err := deps.Store.AdminPrincipalFor(r.Context(), userID)
	if err != nil {
		writeError(w, r, http.StatusUnauthorized, errCodeUnauth)
		return adminPrincipal{}, false
	}
	p.AdminPrincipal = dbp
	return p, true
}

// isAdmin reports whether the caller may use admin oversight at all.
func (p adminPrincipal) isAdmin() bool {
	return p.PlatformAdmin || p.Role == "SUPER_ADMIN" || p.Role == "WORKSPACE_ADMIN"
}

// adminScope is what an admin may oversee: any workspace (platform admin) or
// an explicit set. listing is the default set for an unfiltered listing.
type adminScope struct {
	any     bool
	ids     []string
	listing []string
}

func (s adminScope) allows(ws string) bool { return s.any || slices.Contains(s.ids, ws) }

// adminScopeWorkspaces mirrors the control-plane Authorizer/visible_workspaces:
// a platform admin may open any workspace (its default listing is its own org,
// or every org when it has none); SUPER_ADMIN → its own org only;
// WORKSPACE_ADMIN → its effective workspaces; anyone else is forbidden.
func adminScopeWorkspaces(r *http.Request, deps Deps, p adminPrincipal) (adminScope, bool, error) {
	ctx := r.Context()
	switch {
	case p.PlatformAdmin:
		var ids []string
		var err error
		if p.OrgID != "" {
			ids, err = deps.Store.AdminOrgWorkspaceIDs(ctx, p.OrgID)
		} else {
			ids, err = deps.Store.AllWorkspaceIDs(ctx)
		}
		return adminScope{any: true, listing: ids}, true, err
	case p.Role == "SUPER_ADMIN":
		ids, err := deps.Store.AdminOrgWorkspaceIDs(ctx, p.OrgID)
		return adminScope{ids: ids, listing: ids}, true, err
	case p.Role == "WORKSPACE_ADMIN":
		ids, err := deps.Store.AdminWorkspaceIDsForUser(ctx, p.userID)
		return adminScope{ids: ids, listing: ids}, true, err
	default:
		return adminScope{}, false, nil
	}
}

// adminListConversationsHandler: GET /api/v1/admin/conversations — every
// conversation in the admin's scope (oversight). STAFF is forbidden.
func adminListConversationsHandler(cfg config.Config, deps Deps, logger *slog.Logger) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if deps.Store == nil {
			writeJSON(w, http.StatusOK, []store.AdminConversationSummary{})
			return
		}
		principal, ok := adminClaims(cfg, deps, w, r)
		if !ok {
			return
		}
		access, allowed, err := adminScopeWorkspaces(r, deps, principal)
		if err != nil {
			logger.Error("admin scope", "err", err)
			writeError(w, r, http.StatusBadGateway, errCodeInternal)
			return
		}
		if !allowed {
			writeError(w, r, http.StatusForbidden, errCodeForbidden)
			return
		}
		scope := access.listing
		// Optional ?workspace_id= filter, constrained to the admin's scope. A
		// workspace outside it answers like an unknown one (no existence leak).
		if want := r.URL.Query().Get("workspace_id"); want != "" {
			if !access.allows(want) {
				writeError(w, r, http.StatusNotFound, errCodeNotFound)
				return
			}
			scope = []string{want}
		}
		if len(scope) == 0 {
			writeJSON(w, http.StatusOK, []store.AdminConversationSummary{})
			return
		}
		limit := 50
		if v := r.URL.Query().Get("limit"); v != "" {
			if n, e := strconv.Atoi(v); e == nil && n > 0 && n <= 200 {
				limit = n
			}
		}
		convs, err := deps.Store.AdminListConversations(r.Context(), scope, limit)
		if err != nil {
			logger.Error("admin list conversations", "err", err)
			writeError(w, r, http.StatusBadGateway, errCodeInternal)
			return
		}
		if convs == nil {
			convs = []store.AdminConversationSummary{}
		}
		writeJSON(w, http.StatusOK, convs)
	}
}

// adminConversationMessagesHandler: GET /api/v1/admin/conversations/{id}/messages
// — full thread of any conversation whose workspace is in the admin's scope.
// Prevents IDOR by checking the conversation's workspace against the scope.
func adminConversationMessagesHandler(cfg config.Config, deps Deps, logger *slog.Logger) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if deps.Store == nil {
			writeJSON(w, http.StatusOK, []store.StoredMessage{})
			return
		}
		principal, ok := adminClaims(cfg, deps, w, r)
		if !ok {
			return
		}
		convID := r.PathValue("id")
		if convID == "" {
			writeError(w, r, http.StatusBadRequest, errCodeBadRequest)
			return
		}
		scope, allowed, err := adminScopeWorkspaces(r, deps, principal)
		if err != nil {
			logger.Error("admin scope", "err", err)
			writeError(w, r, http.StatusBadGateway, errCodeInternal)
			return
		}
		if !allowed {
			writeError(w, r, http.StatusForbidden, errCodeForbidden)
			return
		}
		// Unknown and out-of-scope conversations get the same 404.
		ws, err := deps.Store.AdminConversationWorkspace(r.Context(), convID)
		if err != nil || ws == "" || !scope.allows(ws) {
			writeError(w, r, http.StatusNotFound, errCodeNotFound)
			return
		}
		msgs, err := deps.Store.AdminConversationMessages(r.Context(), convID)
		if err != nil {
			logger.Error("admin conversation messages", "err", err)
			writeError(w, r, http.StatusBadGateway, errCodeInternal)
			return
		}
		if msgs == nil {
			msgs = []store.StoredMessage{}
		}
		writeJSON(w, http.StatusOK, msgs)
	}
}
