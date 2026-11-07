// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"context"
	"log/slog"
	"net/http"
	"time"

	"github.com/alicangunduz/raggie/services/edge/internal/config"
	"github.com/alicangunduz/raggie/services/edge/internal/mcp"
)

// mcpCapabilityTool is one advertised MCP tool in the admin capability response
// (name + description only — no schema, no secrets).
type mcpCapabilityTool struct {
	Name        string `json:"name"`
	Description string `json:"description"`
}

// mcpCapabilityResponse is the pinned admin capability body. It is ALWAYS
// returned with HTTP 200 (fail-soft): status carries the real outcome
// ("ok"|"error"|"disabled"). enabled mirrors whether MCP is wired at all.
type mcpCapabilityResponse struct {
	Enabled         bool                `json:"enabled"`
	Status          string              `json:"status"` // ok | error | disabled
	ProtocolVersion string              `json:"protocol_version"`
	LatencyMs       int64               `json:"latency_ms"`
	CheckedAt       string              `json:"checked_at"` // ISO8601 / RFC3339
	Tools           []mcpCapabilityTool `json:"tools"`
}

// adminMCPCapabilitiesHandler: GET /api/v1/admin/mcp/capabilities?provider=jira
// — a live MCP health + version + tool-list probe for the admin detail page.
// Reuses the admin auth (SUPER_ADMIN / WORKSPACE_ADMIN). It times one
// ListTools/HealthCheck (the handshake doubles as health + version) and returns
// the pinned 200 body. Fail-soft: never 503 — disabled/error are carried in the
// status field so the UI can render the honest connected-vs-flag split.
func adminMCPCapabilitiesHandler(cfg config.Config, deps Deps, logger *slog.Logger) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		// Admin auth: SUPER_ADMIN, WORKSPACE_ADMIN or platform admin (STAFF
		// forbidden), resolved from the database. This is the only hard gate;
		// everything past it is fail-soft 200.
		principal, ok := adminClaims(cfg, deps, w, r)
		if !ok {
			return // adminClaims already wrote 401
		}
		if !principal.isAdmin() {
			writeError(w, r, http.StatusForbidden, errCodeForbidden)
			return
		}

		// provider is informational for now (only jira exists); default to jira.
		provider := r.URL.Query().Get("provider")
		if provider == "" {
			provider = "jira"
		}

		resp := mcpCapabilityResponse{
			Enabled:   deps.MCP != nil,
			Status:    "disabled",
			CheckedAt: time.Now().UTC().Format(time.RFC3339),
			Tools:     []mcpCapabilityTool{},
		}

		// MCP not wired (global flag off / nil provider) → honest "disabled".
		if deps.MCP == nil {
			writeJSON(w, http.StatusOK, resp)
			return
		}

		// Time one probe. Prefer the richer VersionedProvider (version + latency);
		// fall back to a plain ListTools when only the base interface is available.
		ctx, cancel := context.WithTimeout(r.Context(), 20*time.Second)
		defer cancel()

		if vp, hasV := deps.MCP.(mcp.VersionedProvider); hasV {
			start := time.Now()
			defs, lerr := vp.RefreshTools(ctx)
			resp.LatencyMs = time.Since(start).Milliseconds()
			resp.ProtocolVersion = vp.ProtocolVersion()
			if lerr != nil {
				logger.Warn("admin mcp tools/list failed", "err", lerr, "provider", provider)
				resp.Status = "error"
				writeJSON(w, http.StatusOK, resp)
				return
			}
			resp.Status = "ok"
			resp.Tools = toCapabilityTools(defs)
			writeJSON(w, http.StatusOK, resp)
			return
		}

		// Base provider only: time a ListTools ourselves (handshake + list).
		start := time.Now()
		defs, lerr := deps.MCP.ListTools(ctx)
		resp.LatencyMs = time.Since(start).Milliseconds()
		if lerr != nil {
			logger.Warn("admin mcp tools/list failed", "err", lerr, "provider", provider)
			resp.Status = "error"
			writeJSON(w, http.StatusOK, resp)
			return
		}
		resp.Status = "ok"
		resp.Tools = toCapabilityTools(defs)
		writeJSON(w, http.StatusOK, resp)
	}
}

// toCapabilityTools maps MCP tool defs to the safe name+description view.
func toCapabilityTools(defs []mcp.ToolDef) []mcpCapabilityTool {
	out := make([]mcpCapabilityTool, 0, len(defs))
	for _, d := range defs {
		out = append(out, mcpCapabilityTool{Name: d.Name, Description: d.Description})
	}
	return out
}
