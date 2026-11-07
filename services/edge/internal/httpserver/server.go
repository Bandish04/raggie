// SPDX-License-Identifier: Apache-2.0

// Package httpserver wires the edge HTTP surface: health plus the RAG
// chat-stream endpoint (POST /api/v1/chat/stream, SSE). Metrics are served on a
// separate internal listener (NewMetricsServer).
package httpserver

import (
	"context"
	"crypto/subtle"
	"encoding/json"
	"log/slog"
	"net/http"
	"os"
	"strconv"
	"time"

	"github.com/alicangunduz/raggie/services/edge/internal/bus"
	"github.com/alicangunduz/raggie/services/edge/internal/config"
	"github.com/alicangunduz/raggie/services/edge/internal/mcp"
	"github.com/alicangunduz/raggie/services/edge/internal/ports"
	"github.com/alicangunduz/raggie/services/edge/internal/rag"
	"github.com/alicangunduz/raggie/services/edge/internal/ratelimit"
	"github.com/alicangunduz/raggie/services/edge/internal/store"
)

// WorkspaceInfoPort exposes the workspace attributes the edge needs to enforce
// A4 (widget audience + per-workspace CORS) and the authoritative access check
// (UserCanAccessWorkspace: active user AND platform admin, in-org SUPER_ADMIN,
// or effective membership). Satisfied by *store.Store; an interface so the
// widget handlers can be tested without a database.
type WorkspaceInfoPort interface {
	WorkspaceWidget(ctx context.Context, workspaceID string) (
		typ string, corsOrigins []string, primaryColor, name string, err error)
	UserCanAccessWorkspace(ctx context.Context, userID, workspaceID string) (bool, error)
}

// TokenStatePort checks the server-side session referenced by an admin JWT.
// Production wires the Postgres store so logout/deactivation takes effect on
// the edge immediately instead of waiting for token expiry.
type TokenStatePort interface {
	UserSessionActive(ctx context.Context, userID, sessionID string) (bool, error)
}

// ChatPolicyPort resolves trusted workspace defaults and a current immutable
// skill snapshot. Production is satisfied by *store.Store.
type ChatPolicyPort interface {
	ResolveChatPolicy(
		ctx context.Context,
		userID, workspaceID, skillID string,
		skillVersion int,
	) (store.ChatPolicy, error)
}

// ReadinessPort is implemented by required runtime dependencies.
type ReadinessPort interface {
	Ready(ctx context.Context) error
}

type ReadinessCheck struct {
	Name     string
	Probe    ReadinessPort
	Required bool
}

// JiraGatePort reports whether a workspace's org has a connected `jira`
// integration (the coarse Phase-1 gate for MCP Jira tools). Satisfied by
// *store.Store; an interface so the tools loop can be tested without a database.
type JiraGatePort interface {
	HasConnectedJira(ctx context.Context, workspaceID string) (bool, error)
}

// Deps holds the chat hot-path collaborators. RAG/Chat are required; Bus is
// optional (nil disables events). WSInfo resolves workspace type, membership
// and widget origins: without it (no database) the chat and run-task endpoints
// refuse with 503 rather than serve unauthenticated, and widget tokens are not
// issued.
type Deps struct {
	RAG         *rag.RAGService
	Chat        ports.ChatProvider
	Models      ports.ModelLister // optional provider model discovery (GET /api/v1/models)
	Store       *store.Store
	Bus         *bus.Bus
	WSInfo      WorkspaceInfoPort
	TokenState  TokenStatePort
	ChatPolicy  ChatPolicyPort
	Readiness   []ReadinessCheck
	Background  *BackgroundJobs
	Web         ports.WebSearcher   // optional web-search fallback (nil disables it)
	WebResearch ports.WebResearcher // optional enriched web evidence path
	WebReranker ports.Reranker      // optional cross-encoder ranking for web evidence (also feeds the rerank fail-open metric)
	MCP         mcp.ToolProvider    // optional MCP tool provider (nil disables tool-use)
	// Drain coordinates graceful shutdown of SSE streams (readiness flip, new
	// stream rejection, reconnect on forced cancel). Nil disables draining.
	Drain *Drainer
	// Streams caps concurrent chat SSE streams per replica
	// (EDGE_MAX_SSE_CONNECTIONS); nil admits everything.
	Streams *StreamLimiter
	// RateLimiter enforces the per-user / per-widget-session / per-IP limits
	// (Redis-backed in production). Nil disables rate limiting.
	RateLimiter ratelimit.Limiter
	// JiraGate gates MCP Jira tools per-org. Optional: when nil the handler falls
	// back to Store (production wires Store, which satisfies it). An explicit
	// interface seam so the tools loop is testable without a database.
	JiraGate JiraGatePort
	// Memory stores durable per-user memory and Features reads per-workspace
	// chat-intelligence flags. Optional seams: when nil they fall back to Store
	// (which implements both), so the gates are testable without a database.
	Memory   MemoryPort
	Features FeaturesPort

	// unauthenticatedHotPath serves chat without WSInfo and therefore WITHOUT
	// authentication. Unexported on purpose: only this package's tests can set
	// it (cmd/edge cannot), to exercise the hot path without a database.
	unauthenticatedHotPath bool
}

// MemoryPort is durable per-user memory (facts mined from earlier chats).
type MemoryPort interface {
	GetUserMemory(ctx context.Context, userID string, limit int) ([]string, error)
	AddUserMemory(ctx context.Context, userID string, facts []string) error
}

// FeaturesPort reads a workspace's chat-intelligence flags.
type FeaturesPort interface {
	WorkspaceFeatures(ctx context.Context, workspaceID string) (store.WorkspaceFeatureFlags, error)
}

// memoryStore returns the configured memory store, or nil.
func (d Deps) memoryStore() MemoryPort {
	if d.Memory != nil {
		return d.Memory
	}
	if d.Store != nil {
		return d.Store
	}
	return nil
}

// workspaceFeatures returns the workspace's flags. With no source every flag
// is off; on a read error memory is forced off (fail closed) while the other
// flags keep what the source returned.
func (d Deps) workspaceFeatures(ctx context.Context, workspaceID string) store.WorkspaceFeatureFlags {
	var src FeaturesPort = d.Features
	if src == nil && d.Store != nil {
		src = d.Store
	}
	if src == nil {
		return store.WorkspaceFeatureFlags{}
	}
	f, err := src.WorkspaceFeatures(ctx, workspaceID)
	if err != nil {
		f.Memory = false
	}
	return f
}

// memoryAllowed is the single memory gate: the global kill switch, the
// per-workspace flag and an authenticated user (widget sessions and the
// unauthenticated hot path have no userID, so they never get memory).
func memoryAllowed(cfg config.Config, feats store.WorkspaceFeatureFlags, userID string, deps Deps) bool {
	return cfg.MemoryEnabled && feats.Memory && userID != "" && deps.memoryStore() != nil
}

// chatAuthUnavailable reports whether chat must be refused because nothing can
// authorize it (no WSInfo, i.e. no database).
func (d Deps) chatAuthUnavailable() bool { return d.WSInfo == nil && !d.unauthenticatedHotPath }

// route is one registration on the public mux. Keeping the table explicit
// lets the authz matrix test enumerate every route and fail on any route that
// has no expected-policy entry.
type route struct {
	pattern string // "METHOD /path" (net/http ServeMux pattern)
	handler http.Handler
}

// routes returns every route served on the public listener, in registration
// order. /metrics is NOT here: it lives on the internal listener
// (metricsRoutes).
func routes(cfg config.Config, logger *slog.Logger, deps Deps) []route {
	var rs []route
	add := func(pattern string, h any) {
		switch h := h.(type) {
		case http.Handler:
			rs = append(rs, route{pattern, h})
		case func(http.ResponseWriter, *http.Request):
			rs = append(rs, route{pattern, http.HandlerFunc(h)})
		default:
			panic("routes: unsupported handler type for " + pattern)
		}
	}

	add("GET /healthz", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"status": "ok", "service": "edge"})
	})

	add("GET /readyz", readinessHandler(cfg, deps.Readiness, deps.Drain, logger))

	add("POST /api/v1/chat/stream", chatHandler(cfg, deps, logger))

	// AI-generate a skill's instructions (system prompt) from a short user
	// description (authenticated INTERNAL users; one-shot non-streamed completion).
	add("POST /api/v1/skills/generate-instructions", generateInstructionsHandler(cfg, deps, logger))

	// Scheduled tasks. run-task is server-to-server (scheduler worker → edge,
	// shared X-Internal-Secret): execute ONE task headlessly and return the answer
	// (no SSE, no conversation persisted). schedule/parse is user-facing
	// (aud=admin): parse a natural-language schedule into {cron, prompt, name,
	// summary}. Both drain a one-shot completion on the chat pool.
	add("POST /api/v1/internal/run-task", runTaskHandler(cfg, deps, logger))
	add("POST /api/v1/schedule/parse", scheduleParseHandler(cfg, deps, logger))

	// Provider model discovery (admin): the chat models the upstream exposes.
	add("GET /api/v1/models", modelsHandler(cfg, deps, logger))

	// Chat history (authenticated INTERNAL users): list conversations + replay one.
	add("GET /api/v1/conversations", listConversationsHandler(cfg, deps, logger))
	add("GET /api/v1/conversations/{id}/messages", conversationMessagesHandler(cfg, deps, logger))
	add("DELETE /api/v1/conversations/{id}", deleteConversationHandler(cfg, deps, logger))
	add("DELETE /api/v1/conversations", deleteAllConversationsHandler(cfg, deps, logger))
	add("POST /api/v1/messages/{id}/feedback", messageFeedbackHandler(cfg, deps, logger))

	// Admin oversight: read ANY conversation in scope (SUPER_ADMIN / WORKSPACE_ADMIN).
	add("GET /api/v1/admin/conversations", adminListConversationsHandler(cfg, deps, logger))
	add("GET /api/v1/admin/conversations/{id}/messages", adminConversationMessagesHandler(cfg, deps, logger))

	// Admin MCP capability detail: live health + version + tool list for the
	// connected provider (SUPER_ADMIN / WORKSPACE_ADMIN; always 200, fail-soft).
	add("GET /api/v1/admin/mcp/capabilities", adminMCPCapabilitiesHandler(cfg, deps, logger))

	// External widget (A4): public, EXTERNAL-only token issuance + the loader and
	// Shadow-DOM bundle served from the public edge (not the admin backend).
	add("POST /api/v1/widget/token", widgetTokenHandler(cfg, deps, logger))
	add("OPTIONS /api/v1/widget/token", widgetPreflightHandler(deps))
	// The widget's chat POST (Authorization + JSON) is preflighted by browsers.
	add("OPTIONS /api/v1/chat/stream", widgetPreflightHandler(deps))
	if dir := cfg.WidgetStaticDir; dir != "" {
		if _, err := os.Stat(dir); err == nil {
			add("GET /widgets/", http.StripPrefix("/widgets/", http.FileServer(http.Dir(dir))))
		}
	}
	return rs
}

// New builds the edge HTTP server.
func New(cfg config.Config, logger *slog.Logger, deps Deps) *http.Server {
	mux := http.NewServeMux()
	for _, rt := range routes(cfg, logger, deps) {
		mux.Handle(rt.pattern, rt.handler)
	}

	handler := chain(mux, requestID, withLocale(cfg.DefaultLocale),
		withBodyReadTimeout(time.Duration(cfg.HTTPBodyReadTimeoutSeconds)*time.Second),
		logging(logger), recoverer(logger))

	return &http.Server{
		Addr:    ":" + cfg.Port,
		Handler: handler,
		// Slow-header (slowloris) protection and idle keep-alive reaping. Bodies
		// are bounded per endpoint with http.MaxBytesReader.
		ReadHeaderTimeout: 10 * time.Second,
		IdleTimeout:       120 * time.Second,
		MaxHeaderBytes:    64 << 10,
		// Intentionally no ReadTimeout/WriteTimeout: SSE streams are long-lived;
		// stream lifetime is bounded by the client context and the shutdown drain.
	}
}

// NewMetricsServer builds the internal-only metrics listener (METRICS_ADDR).
// /metrics is deliberately absent from the public mux: it exposes operational
// counters and must only be reachable by the scraper. When METRICS_TOKEN is
// set the scraper must also present it as a bearer token.
func NewMetricsServer(cfg config.Config, logger *slog.Logger, deps Deps) *http.Server {
	mux := http.NewServeMux()
	for _, rt := range metricsRoutes(cfg, deps) {
		mux.Handle(rt.pattern, rt.handler)
	}
	return &http.Server{
		Addr:              cfg.MetricsAddr,
		Handler:           chain(mux, withLocale(cfg.DefaultLocale), recoverer(logger)),
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       10 * time.Second,
		WriteTimeout:      10 * time.Second,
		IdleTimeout:       60 * time.Second,
	}
}

// metricsRoutes returns the routes of the internal metrics listener.
func metricsRoutes(cfg config.Config, deps Deps) []route {
	metrics := metricsHandler(deps)
	return []route{{"GET /metrics", http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if cfg.MetricsToken != "" &&
			subtle.ConstantTimeCompare([]byte(bearer(r)), []byte(cfg.MetricsToken)) != 1 {
			w.Header().Set("WWW-Authenticate", "Bearer")
			writeError(w, r, http.StatusUnauthorized, errCodeUnauth)
			return
		}
		metrics(w, r)
	})}}
}

func metricsHandler(deps Deps) http.HandlerFunc {
	return func(w http.ResponseWriter, _ *http.Request) {
		// Minimal hand-written Prometheus exposition (no client library dependency).
		w.Header().Set("Content-Type", "text/plain; version=0.0.4")
		body := "# HELP raggie_edge_up 1 if the edge process is up\n" +
			"# TYPE raggie_edge_up gauge\n" +
			"raggie_edge_up 1\n"
		// MCP CallTool counters (when an MCP provider exposing them is wired).
		if cm, ok := deps.MCP.(interface{ Counters() (int64, int64) }); ok {
			total, errs := cm.Counters()
			body += "# HELP raggie_mcp_tool_calls_total total MCP tools/call invocations\n" +
				"# TYPE raggie_mcp_tool_calls_total counter\n" +
				"raggie_mcp_tool_calls_total " + strconv.FormatInt(total, 10) + "\n" +
				"# HELP raggie_mcp_tool_call_errors_total MCP tools/call invocations that errored\n" +
				"# TYPE raggie_mcp_tool_call_errors_total counter\n" +
				"raggie_mcp_tool_call_errors_total " + strconv.FormatInt(errs, 10) + "\n"
		}
		// Reranker fail-opens (the same client backs RAG and web-evidence ranking).
		if rc, ok := deps.WebReranker.(interface{ FailOpenTotal() int64 }); ok {
			body += "# HELP raggie_edge_rerank_fail_open_total rerank calls that failed open (fused order kept)\n" +
				"# TYPE raggie_edge_rerank_fail_open_total counter\n" +
				"raggie_edge_rerank_fail_open_total " + strconv.FormatInt(rc.FailOpenTotal(), 10) + "\n"
		}
		if deps.Drain != nil {
			draining := "0"
			if deps.Drain.Draining() {
				draining = "1"
			}
			body += "# HELP raggie_edge_active_streams in-flight chat SSE streams\n" +
				"# TYPE raggie_edge_active_streams gauge\n" +
				"raggie_edge_active_streams " + strconv.Itoa(deps.Drain.Active()) + "\n" +
				"# HELP raggie_edge_draining 1 while the replica drains for shutdown\n" +
				"# TYPE raggie_edge_draining gauge\n" +
				"raggie_edge_draining " + draining + "\n"
		}
		if deps.Streams != nil {
			open, limit, rejected := deps.Streams.Stats()
			body += "# HELP raggie_edge_sse_streams chat SSE streams holding a slot under EDGE_MAX_SSE_CONNECTIONS\n" +
				"# TYPE raggie_edge_sse_streams gauge\n" +
				"raggie_edge_sse_streams " + strconv.FormatInt(open, 10) + "\n" +
				"# HELP raggie_edge_sse_streams_limit per-replica stream cap (0 = unlimited)\n" +
				"# TYPE raggie_edge_sse_streams_limit gauge\n" +
				"raggie_edge_sse_streams_limit " + strconv.FormatInt(limit, 10) + "\n" +
				"# HELP raggie_edge_sse_streams_rejected_total chats shed with busy at the stream cap\n" +
				"# TYPE raggie_edge_sse_streams_rejected_total counter\n" +
				"raggie_edge_sse_streams_rejected_total " + strconv.FormatInt(rejected, 10) + "\n"
		}
		if deps.Background != nil {
			active, dropped := deps.Background.Stats()
			body += "# HELP raggie_background_jobs_active currently running bounded background jobs\n" +
				"# TYPE raggie_background_jobs_active gauge\n" +
				"raggie_background_jobs_active " + strconv.FormatInt(active, 10) + "\n" +
				"# HELP raggie_background_jobs_dropped_total background jobs shed due to capacity or shutdown\n" +
				"# TYPE raggie_background_jobs_dropped_total counter\n" +
				"raggie_background_jobs_dropped_total " + strconv.FormatInt(dropped, 10) + "\n"
		}
		body += runtimeMetrics()
		_, _ = w.Write([]byte(body))
	}
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}
