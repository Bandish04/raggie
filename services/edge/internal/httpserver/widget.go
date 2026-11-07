// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"errors"
	"log/slog"
	"net/http"
	"slices"
	"strings"
	"time"

	"github.com/alicangunduz/raggie/services/edge/internal/config"
	"github.com/alicangunduz/raggie/services/edge/internal/widgetauth"
)

// bearer extracts a bearer token from the Authorization header ("" if absent).
func bearer(r *http.Request) string {
	if after, ok := strings.CutPrefix(r.Header.Get("Authorization"), "Bearer "); ok {
		return after
	}
	return ""
}

type widgetTokenRequest struct {
	WorkspaceID string `json:"workspace_id"`
}

type widgetTokenResponse struct {
	Token        string `json:"token"`
	PrimaryColor string `json:"primary_color"`
	Name         string `json:"name"`
	ExpiresIn    int    `json:"expires_in"`
}

// widgetTokenHandler issues a short-lived aud=widget token for an EXTERNAL
// workspace, but only to an Origin on that workspace's CORS allow-list (A4, ARCHITECTURE §9):
// physical surface (public edge) + audience scope + EXTERNAL-type check + exact
// per-workspace origin (wildcards are never stored, so they can never match).
func widgetTokenHandler(cfg config.Config, deps Deps, logger *slog.Logger) http.HandlerFunc {
	ttl := time.Duration(cfg.WidgetTokenTTLSeconds) * time.Second
	return func(w http.ResponseWriter, r *http.Request) {
		if deps.WSInfo == nil {
			writeError(w, r, http.StatusServiceUnavailable, errCodeUnavailable)
			return
		}
		var req widgetTokenRequest
		if err := decodeJSONBody(w, r, smallJSONBodyBytes, &req); errors.Is(err, errBodyTooLarge) {
			writeError(w, r, http.StatusRequestEntityTooLarge, errCodeTooLarge)
			return
		} else if err != nil || !uuidLike(req.WorkspaceID) {
			// Not a UUID: refused before it costs a lookup or a rate-limit key.
			writeError(w, r, http.StatusBadRequest, errCodeBadRequest)
			return
		}

		// Issuance limits per IP+workspace and per IP across all workspaces (the
		// workspace id is client-chosen), charged before the workspace lookup so
		// a token-minting loop cannot hammer the database either.
		ip := clientIP(r, cfg.TrustedProxyCIDRs)
		if d, ok := checkRateLimits(r.Context(), deps.RateLimiter, logger,
			rateLimitCheck{"wtok:" + req.WorkspaceID + ":" + ip, cfg.RateLimitWidgetTokenPerMinute},
			rateLimitCheck{"wtokip:" + ip, cfg.RateLimitWidgetTokenIPPerMinute},
		); !ok {
			allowOriginForError(w, r)
			setRetryAfter(w, d.RetryAfter)
			writeError(w, r, http.StatusTooManyRequests, errCodeRateLimited)
			return
		}

		typ, corsOrigins, color, name, err := deps.WSInfo.WorkspaceWidget(r.Context(), req.WorkspaceID)
		// Unknown or non-EXTERNAL workspaces are indistinguishable to the public
		// surface (no enumeration; INTERNAL workspaces are never reachable here).
		if err != nil || typ != "EXTERNAL" {
			writeError(w, r, http.StatusNotFound, errCodeNotFound)
			return
		}

		origin := r.Header.Get("Origin")
		if origin == "" || !slices.Contains(corsOrigins, origin) {
			writeError(w, r, http.StatusForbidden, errCodeForbidden)
			return
		}

		token, err := widgetauth.Mint(cfg.WidgetTokenSecret, req.WorkspaceID, ttl, time.Now())
		if err != nil {
			logger.Error("mint widget token", "err", err)
			writeError(w, r, http.StatusInternalServerError, errCodeInternal)
			return
		}

		allowOrigin(w, origin)
		writeJSON(w, http.StatusOK, widgetTokenResponse{
			Token:        token,
			PrimaryColor: color,
			Name:         name,
			ExpiresIn:    cfg.WidgetTokenTTLSeconds,
		})
	}
}

// widgetPreflightHandler answers CORS preflight for the widget endpoints
// (token issuance and chat stream). It
// reflects the requesting Origin; the POST itself still enforces the
// workspace-scoped allow-list, so preflight grants no data access.
func widgetPreflightHandler(_ Deps) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if origin := r.Header.Get("Origin"); origin != "" {
			allowOrigin(w, origin)
			w.Header().Set("Access-Control-Allow-Methods", "POST, OPTIONS")
			w.Header().Set("Access-Control-Allow-Headers", "Content-Type, Authorization, Idempotency-Key")
			w.Header().Set("Access-Control-Max-Age", "600")
		}
		w.WriteHeader(http.StatusNoContent)
	}
}

// exposedHeaders are the response headers a cross-origin widget script may
// read (Retry-After drives its 429/503 back-off).
const exposedHeaders = "Retry-After, X-Request-Id"

// allowOrigin echoes a single, explicit origin (never "*") so credentials and
// per-workspace isolation hold, and exposes the headers the widget reads.
func allowOrigin(w http.ResponseWriter, origin string) {
	h := w.Header()
	h.Set("Access-Control-Allow-Origin", origin)
	h.Set("Access-Control-Expose-Headers", exposedHeaders)
	h.Add("Vary", "Origin")
}

// allowOriginForError makes a generic error readable cross-origin when it is
// written BEFORE the workspace allow-list could be checked (rate limiting
// ahead of the database lookup, shutdown draining ahead of body parsing). The
// body is the user-safe error contract only, and widget requests carry no
// cookies, so reflecting the Origin discloses nothing; it only lets the widget
// read the status and Retry-After.
func allowOriginForError(w http.ResponseWriter, r *http.Request) {
	if origin := r.Header.Get("Origin"); origin != "" {
		allowOrigin(w, origin)
	}
}
