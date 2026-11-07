// SPDX-License-Identifier: Apache-2.0

// Package config loads the edge service configuration from the environment.
package config

import (
	"encoding/json"
	"fmt"
	"log/slog"
	"net/netip"
	"net/url"
	"os"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/alicangunduz/raggie/services/edge/internal/locale"
)

const (
	CapabilityReasoning = "reasoning"
	CapabilityTools     = "tools"
	CapabilityVision    = "vision"
)

var envNamePattern = regexp.MustCompile(`^[A-Z_][A-Z0-9_]*$`)

// DefaultChatMaxBodyBytes fits four 5MB base64 image attachments plus the text
// fields of a chat request.
const DefaultChatMaxBodyBytes = 21 << 20

// minSecretBytes is the minimum length of a shared HMAC/API secret outside
// development (256 bits of entropy when randomly generated as raw bytes).
const minSecretBytes = 32

// knownDefaultSecrets are placeholders shipped in code, .env.example and the
// k8s base config. Booting production with any of them is a misconfiguration.
var knownDefaultSecrets = map[string]bool{
	"dev-insecure-widget-secret-change-me-please": true,
	"dev-insecure-jwt-secret-change-me-please":    true,
	"change-me-to-a-random-32-byte-min-secret":    true,
	"change-me": true,
	"changeme":  true,
	"secret":    true,
}

// ModelProfile maps one stable product-facing model id to an OpenAI-compatible
// provider endpoint and its provider-native model id. APIKeyEnv names the secret
// env var; APIKey is resolved at boot and is never serialized or exposed.
type ModelProfile struct {
	ID             string   `json:"id"`
	Provider       string   `json:"provider"`
	BaseURL        string   `json:"base_url"`
	APIKeyEnv      string   `json:"api_key_env,omitempty"`
	UpstreamModel  string   `json:"upstream_model,omitempty"`
	MaxConcurrency int      `json:"max_concurrency,omitempty"`
	MaxTokens      int      `json:"max_tokens,omitempty"`
	Capabilities   []string `json:"capabilities,omitempty"`
	// ResponseHeaderTimeoutSeconds overrides LLMAAS_RESPONSE_HEADER_TIMEOUT_SECONDS
	// for this provider (0 inherits it). All models of a provider must agree.
	ResponseHeaderTimeoutSeconds int    `json:"response_header_timeout_seconds,omitempty"`
	APIKey                       string `json:"-"`
}

func (p ModelProfile) Supports(capability string) bool {
	return slices.Contains(p.Capabilities, capability)
}

// Config holds the edge service runtime configuration.
type Config struct {
	Port     string
	LogLevel string

	// Env is RAGGIE_ENV. Anything other than a development value (see
	// IsDevelopment) is treated as production: Validate then refuses to boot with
	// default/weak secrets. Unset means production (secure by default).
	Env string

	// DefaultLocale is the fallback language of server-authored text (error
	// messages, prompt templates) when a request carries no locale signal.
	// DEFAULT_LOCALE, else the web's NEXT_PUBLIC_DEFAULT_LOCALE (shared .env),
	// else "en". The model still answers in the language of the question.
	DefaultLocale locale.Locale

	// DefaultTimezone is the IANA zone assumed when a schedule request carries
	// none: DEFAULT_TIMEZONE (shared with control-plane and workers), else UTC.
	DefaultTimezone string

	// Chat LLMaaS (OpenAI-compatible /v1). The answer is in delta.content; the
	// chain-of-thought arrives in a separate "reasoning" field and is only relayed
	// to clients when STREAM_REASONING is on.
	LLMaaSBaseURL string
	LLMaaSAPIKey  string
	ChatModel     string
	ChatMaxTokens int

	// ReasoningEffort is the DEFAULT chain-of-thought depth for reasoning models
	// ("low"|"medium"|"high"), sent as "reasoning_effort". A valid per-request
	// value overrides it; an invalid one falls back here. gpt-oss reasons
	// regardless — this only tunes how deeply.
	ReasoningEffort string

	// ModelProfiles enables provider-aware routing when
	// LLM_MODEL_PROFILES_JSON is set. Canonical model ids may map to different
	// endpoints/upstream ids and each provider gets an independent concurrency
	// pool. The legacy single-provider settings above remain the fallback when
	// the registry is absent.
	ModelProfiles         []ModelProfile
	ModelRegistryExplicit bool
	ModelProfilesError    string

	// Embeddings come from the on-prem embeddings gateway (services/embeddings),
	// which also hosts the reranker. It is authenticated with InternalAPISecret,
	// never with the LLM provider key.
	EmbeddingsBaseURL string
	// EmbedQueryTimeoutMS bounds one query-embedding call (POST /v1/query) on the
	// chat hot path. RerankTimeoutMS bounds one rerank call; the reranker fails
	// open, so a timeout only costs the rerank, never the answer.
	EmbedQueryTimeoutMS int
	RerankTimeoutMS     int

	// Bounded outbound concurrency to the shared upstream (the true A5 ceiling).
	ChatMaxConcurrency  int
	EmbedMaxConcurrency int

	// EdgeMaxSSEConnections caps concurrent chat SSE streams per replica
	// (EDGE_MAX_SSE_CONNECTIONS, default 12500, 0 = unlimited). Past it new
	// chats get a retryable 503 busy before any stream byte.
	EdgeMaxSSEConnections int

	// LLMResponseHeaderTimeoutSeconds bounds the wait for an LLM endpoint's
	// response headers (first byte) — LLMAAS_RESPONSE_HEADER_TIMEOUT_SECONDS,
	// default 60, [5,900]. Slow local models (CPU Ollama) need more. Only the
	// LLM transports use it; other dependencies keep their own budgets.
	LLMResponseHeaderTimeoutSeconds int

	QdrantURL string
	// QdrantAPIKey is sent as the `api-key` header on every Qdrant request when
	// set (Qdrant's service.api_key). Empty sends no header.
	QdrantAPIKey            string
	ReadinessTimeoutSeconds int

	// DatabaseURL is required outside development: chat authorization (workspace
	// type, membership, token revocation) is resolved from Postgres, and without
	// it the chat endpoints refuse to serve (503). RedisURL is optional (events,
	// idempotency, rate limiting).
	DatabaseURL string
	RedisURL    string

	// Redis Sentinel (HA). When REDIS_SENTINEL_ADDRS and REDIS_SENTINEL_MASTER
	// are both set the edge uses a Sentinel-aware failover client and ignores
	// REDIS_URL. RedisPassword authenticates to the Redis data nodes (also
	// applied in REDIS_URL mode when the URL carries none); RedisSentinelPassword
	// authenticates to the Sentinels.
	RedisSentinelAddrs    []string
	RedisSentinelMaster   string
	RedisPassword         string
	RedisSentinelPassword string
	RedisDB               int

	// External widget (A4). Widget tokens are aud=widget, signed with this secret
	// (shared with the control-plane env so both speak the same scope). The static
	// dir holds the built loader (embed.js) + Shadow-DOM bundle served at /widgets/.
	WidgetTokenSecret     string
	WidgetTokenTTLSeconds int
	WidgetStaticDir       string

	// Shared with the control-plane: verifies aud=admin access tokens that gate
	// the internal chat path (INTERNAL workspaces).
	JWTSecret string

	// InternalAPISecret is a server-to-server shared secret guarding the internal
	// task-execution endpoint (POST /api/v1/internal/run-task), called by the
	// scheduled-tasks worker. Empty disables the endpoint (503): the feature is
	// off until an operator sets INTERNAL_API_SECRET. The request must carry it in
	// the X-Internal-Secret header (constant-time compared). When set, the edge
	// also presents it as `Authorization: Bearer` to the embeddings gateway,
	// which requires it whenever the secret is set (and always in cloud mode);
	// empty sends no Authorization header.
	InternalAPISecret string

	// MetricsAddr is the dedicated listener for GET /metrics. It is never served
	// on the public port. Default 127.0.0.1:9090 (pod/host-local); set ":9090" so
	// an in-cluster Prometheus can scrape it. MetricsToken, when set, additionally
	// requires `Authorization: Bearer <token>` on that listener.
	MetricsAddr  string
	MetricsToken string

	// ChatMaxBodyBytes caps the POST /api/v1/chat/stream JSON body. The default
	// fits the maximum vision payload (4 images x 5MB base64) plus text; lower it
	// (e.g. 262144) when VISION_MODELS is unused.
	ChatMaxBodyBytes int64

	// StreamReasoning relays the model's raw chain-of-thought to clients on the
	// SSE `thinking` channel. Default OFF: raw reasoning can contain retrieved
	// context, system-prompt fragments or unvetted claims.
	StreamReasoning bool

	// Rate limiting (Redis-backed sliding window; fail-open when Redis is down).
	// Limits are requests per minute; 0 disables that individual limit.
	RateLimitEnabled                    bool
	RateLimitChatUserPerMinute          int
	RateLimitChatWidgetSessionPerMinute int
	RateLimitChatWidgetIPPerMinute      int
	RateLimitWidgetTokenPerMinute       int
	// RateLimitWidgetTokenIPPerMinute caps widget-token issuance per client IP
	// across every workspace (RATE_LIMIT_WIDGET_TOKEN_IP_PER_MINUTE, default
	// 30), so rotating the client-chosen workspace_id cannot escape the limit.
	RateLimitWidgetTokenIPPerMinute int

	// HTTPBodyReadTimeoutSeconds bounds how long a client may take to send a
	// JSON request body (HTTP_BODY_READ_TIMEOUT_SECONDS, default 30, [1,600]).
	// It covers the body read only; SSE responses are not affected.
	HTTPBodyReadTimeoutSeconds int
	// TrustedProxyCIDRs lists reverse proxies whose X-Forwarded-For is trusted
	// when deriving the client IP for per-IP limits. Empty = use RemoteAddr.
	TrustedProxyCIDRs []netip.Prefix

	// ShutdownDrainSeconds is how long in-flight SSE streams may run after
	// SIGTERM (readiness already failing, new streams refused) before being
	// cancelled with a "reconnect" event. Keep it below the orchestrator's
	// termination grace period (k8s default 30s).
	ShutdownDrainSeconds int
	// ShutdownDelaySeconds runs BEFORE the drain: readiness already fails but new
	// streams are still served, so endpoint removal can propagate to the load
	// balancer (a preStop-sleep replacement; the image has no shell).
	ShutdownDelaySeconds int
	// TerminationGraceSeconds mirrors the orchestrator's grace period (k8s
	// terminationGracePeriodSeconds); only used to warn when the shutdown
	// budget (delay + drain + tail) cannot fit.
	TerminationGraceSeconds int

	// Conversation memory: how many prior messages (server-side, from the DB) to
	// replay into the LLM context window.
	HistoryMaxMessages int

	// Retrieval tuning. CandidateK chunks are pulled from Qdrant; after optional
	// reranking they are trimmed to ContextK before being placed in the prompt.
	// (Without a reranker, CandidateK == effective recall and the top ContextK by
	// cosine score are kept.)
	RetrieveCandidateK int
	RetrieveContextK   int
	// RetrieveMaxChunksPerDocument is a soft diversity cap applied while packing
	// context. If too few distinct documents exist, skipped high-ranked chunks
	// are used to fill the remaining slots.
	RetrieveMaxChunksPerDocument int

	// RetrieveLowConfidenceScore: when > 0 and the best retrieved chunk scores
	// below it, the model is told the context may be weak (it still answers — we
	// never refuse on a threshold). Default 0 disables the hint; tune per scorer
	// since dense-cosine and rerank score scales differ.
	RetrieveLowConfidenceScore float32

	// RerankEnabled wires the cross-encoder reranker (the embeddings service's
	// /rerank endpoint). Safe to leave on: any failure falls back to dense order.
	RerankEnabled    bool
	RerankCandidateK int

	// PersonalizationEnabled is the GLOBAL kill-switch for injecting the asker's
	// profile (name/title/department/manager/tenure) into the prompt. The profile
	// goes to the EXTERNAL LLM, so it is STILL gated per-workspace
	// (workspaces.personalization_enabled, default OFF) and only for authenticated
	// INTERNAL users — anonymous widget sessions are never personalized. This
	// global flag defaults ON so an admin only has to flip the per-workspace toggle.
	PersonalizationEnabled bool

	// Web search fallback (Brave). GLOBAL kill-switch; the query leaves the
	// on-prem boundary, so default OFF. Effective only when this AND the
	// per-workspace flag are true. Empty BraveAPIKey leaves the searcher nil
	// (feature dormant — fail-open).
	WebSearchEnabled bool
	// WidgetWebSearchEnabled (WIDGET_WEB_SEARCH_ENABLED, default false) lets
	// anonymous widget sessions trigger web/deep research. Searches are paid
	// outbound calls, so the public widget needs this kill switch AND the
	// workspace web_search toggle; internal chats need only the toggle.
	WidgetWebSearchEnabled       bool
	BraveAPIKey                  string
	WebSearchTopN                int
	WebSearchReadEnabled         bool
	WebSearchReadTopN            int
	WebSearchFetchConcurrency    int
	WebSearchFetchTimeoutSeconds int
	WebSearchMaxBodyBytes        int64
	WebSearchCountry             string
	WebSearchLang                string

	// DeepSearchMaxQueries caps the number of sub-queries the deep-research web
	// mode decomposes a question into (the original question always counts as
	// one). Each sub-query is searched SEQUENTIALLY (Brave free-tier rate limit),
	// so this also bounds outbound fan-out. Shares the same gates as web search.
	DeepSearchMaxQueries int

	// DeepSearchTopN is the per-sub-query result count for deep-research Brave
	// calls (vs. WebSearchTopN for the single-web path). Deep mode wants more
	// breadth per query before dedup, so this defaults higher than WebSearchTopN.
	DeepSearchTopN int

	// DeepSearchMaxResults caps the deduped web results gathered across all
	// sub-queries before synthesis — bounds prompt size and keeps citation labels
	// manageable. Set higher than the single-web path because deep mode fans out
	// across more queries.
	DeepSearchMaxResults          int
	DeepSearchParallelism         int
	DeepSearchReadTopN            int
	DeepSearchEvidenceTopK        int
	DeepSearchTotalTimeoutSeconds int
	DeepSearchFollowupRounds      int

	// Vision: the set of chat models that accept image inputs. Empty (default)
	// means no model supports vision and image attachments are dropped (with a
	// short note) — gpt-oss-120b vision is uncertain, so this is opt-in per model
	// via VISION_MODELS (comma-separated, e.g. "qwen3-next-80b-instruct").
	VisionModels map[string]bool

	// ToolModels is the set of chat models that support OpenAI function/tool
	// calling. The unified loop only advertises tools (MCP) to a model in this
	// set; a model that is NOT listed never receives a `tools`/`tool_choice`
	// payload (so a non-tool model can't 4xx mid-stream). Seeded via TOOL_MODELS
	// (comma-separated); the default seeds the current default chat model so MCP
	// works out of the box.
	ToolModels map[string]bool

	// ReasoningModels is the legacy single-provider capability allow-list.
	// Explicit ModelProfiles carry capabilities themselves.
	ReasoningModels map[string]bool

	// MemoryEnabled turns on durable per-user memory: after a turn the edge
	// extracts short facts about the asker and injects them into later chats.
	// The exchange is sent to the EXTERNAL LLM for extraction, but this only
	// happens for authenticated INTERNAL chats (userID != "") — never the widget.
	// This is the GLOBAL kill switch (default ON); like personalization, memory
	// is ALSO gated per workspace (workspaces.memory_enabled, default OFF, so an
	// admin opts each workspace in).
	MemoryEnabled           bool
	MemoryMaxConcurrency    int
	MemoryJobTimeoutSeconds int

	// MCP tool-use (Phase 1: Jira READ tools via a self-hosted mcp-atlassian
	// container). GLOBAL kill-switch, default OFF: when false the chat is
	// byte-for-byte unchanged (no tools advertised, no MCP connection). When on,
	// tools are still gated per-org (a connected `jira` integration must exist).
	MCPEnabled bool
	// MCPAtlassianURL is the streamable-HTTP MCP endpoint of the mcp-atlassian
	// container (internal network only; the edge never holds Jira creds).
	MCPAtlassianURL string
	// MCPMaxIterations caps the agentic tool-calling loop (Stream -> run tools ->
	// Stream ...). Clamped to 1..8.
	MCPMaxIterations int
	// MCPAllowWriteTools exposes MCP tools that are not provably read-only
	// (readOnlyHint, or a read-verb name). Default OFF.
	MCPAllowWriteTools bool

	// AgentUnifiedLoop is the GLOBAL kill-switch for the unified agentic turn.
	// Default OFF: when false the chat handler keeps its legacy
	// three-mutually-exclusive-branches code path (documents / web / deep + the
	// MCP tools loop on the documents path) byte-for-byte. When true, every turn
	// runs through agent.Run: RAG documents are always-on grounding and web /
	// deep / MCP become tools seeded from the per-turn request flags. With the
	// flag on but no tool enabled on a workspace, a turn is exactly ONE Stream
	// call — pure documents RAG, identical to today.
	AgentUnifiedLoop bool
	// HybridContextMode controls which grounding sources are placed in the prompt
	// by default in the unified loop ("best"|"web-only"|"all"). "best" (default)
	// = documents grounding only unless a tool is enabled; "all" would also fold
	// in additional sources. Reserved for per-workspace tuning later.
	HybridContextMode string
	// AgentMaxIterations caps the unified agentic loop. Defaults to
	// MCPMaxIterations (so the two loops share one bound) and is clamped to 1..8.
	AgentMaxIterations int
}

// SupportsVision reports whether the given model may receive image inputs.
func (c Config) SupportsVision(model string) bool {
	if c.ModelRegistryExplicit {
		profile, ok := c.ModelProfile(model)
		return ok && profile.Supports(CapabilityVision)
	}
	return c.VisionModels[model]
}

// SupportsTools reports whether the given model supports OpenAI function/tool
// calling. The unified loop only seeds tools (MCP) when this is true; otherwise
// tools are a no-op (NOT an error) on that model.
func (c Config) SupportsTools(model string) bool {
	if c.ModelRegistryExplicit {
		profile, ok := c.ModelProfile(model)
		return ok && profile.Supports(CapabilityTools)
	}
	return c.ToolModels[model]
}

// SupportsReasoning reports whether reasoning_effort is valid for a model.
func (c Config) SupportsReasoning(model string) bool {
	if c.ModelRegistryExplicit {
		profile, ok := c.ModelProfile(model)
		return ok && profile.Supports(CapabilityReasoning)
	}
	// Hand-built Config values in tests/embedders predate the capability list;
	// preserve their legacy behavior. Config.Load always initializes the map.
	if c.ReasoningModels == nil {
		return true
	}
	return c.ReasoningModels[model]
}

// ModelProfile resolves a canonical model id from the explicit registry.
func (c Config) ModelProfile(model string) (ModelProfile, bool) {
	for _, profile := range c.ModelProfiles {
		if profile.ID == model {
			return profile, true
		}
	}
	return ModelProfile{}, false
}

// HasModel is fail-closed only when an explicit registry is configured. Legacy
// mode preserves dynamic model ids exposed by the single provider, including an
// empty request model which means "use the provider's configured default".
func (c Config) HasModel(model string) bool {
	if !c.ModelRegistryExplicit {
		return true
	}
	_, ok := c.ModelProfile(model)
	return ok
}

// ProviderForModel returns the audit-safe provider identifier.
func (c Config) ProviderForModel(model string) string {
	if profile, ok := c.ModelProfile(model); ok {
		return profile.Provider
	}
	if !c.ModelRegistryExplicit && strings.TrimSpace(model) != "" {
		return "default"
	}
	return ""
}

// SanitizeReasoningEffort returns v if it is one of the allowed values
// (low|medium|high), else "". Shared by config loading and the request handler
// so the allow-list never drifts between them.
func SanitizeReasoningEffort(v string) string {
	switch v {
	case "low", "medium", "high":
		return v
	default:
		return ""
	}
}

// Load reads configuration from environment variables with sane defaults.
func Load() Config {
	cfg := Config{
		Env:                   strings.ToLower(strings.TrimSpace(getenv("RAGGIE_ENV", "production"))),
		DefaultLocale:         defaultLocale(),
		DefaultTimezone:       defaultTimezone(),
		Port:                  getenv("EDGE_PORT", "8080"),
		LogLevel:              getenv("EDGE_LOG_LEVEL", "info"),
		LLMaaSBaseURL:         getenv("LLMAAS_BASE_URL", "https://api.llmaas.example/v1"),
		LLMaaSAPIKey:          getenv("LLMAAS_API_KEY", "change-me"),
		ChatModel:             getenv("LLMAAS_CHAT_MODEL", "gpt-oss-120b"),
		ChatMaxTokens:         getenvInt("LLMAAS_CHAT_MAX_TOKENS", 2048),
		ReasoningEffort:       getenvEnum("LLMAAS_REASONING_EFFORT", "medium", SanitizeReasoningEffort),
		EmbeddingsBaseURL:     getenv("EMBEDDINGS_BASE_URL", "http://embeddings:8002/v1"),
		EmbedQueryTimeoutMS:   clampInt(getenvInt("EMBED_QUERY_TIMEOUT_MS", 8000), 100, 120000),
		RerankTimeoutMS:       clampInt(getenvInt("RERANK_TIMEOUT_MS", 5000), 100, 120000),
		ChatMaxConcurrency:    getenvInt("LLMAAS_CHAT_MAX_CONCURRENCY", 64),
		EmbedMaxConcurrency:   getenvInt("LLMAAS_EMBED_MAX_CONCURRENCY", 32),
		EdgeMaxSSEConnections: max(getenvInt("EDGE_MAX_SSE_CONNECTIONS", 12500), 0),
		LLMResponseHeaderTimeoutSeconds: clampInt(
			getenvInt("LLMAAS_RESPONSE_HEADER_TIMEOUT_SECONDS", 60), 5, 900),
		QdrantURL:               getenv("QDRANT_URL", "http://qdrant:6333"),
		QdrantAPIKey:            getenv("QDRANT_API_KEY", ""),
		ReadinessTimeoutSeconds: clampInt(getenvInt("EDGE_READINESS_TIMEOUT_SECONDS", 3), 1, 30),
		DatabaseURL:             getenv("DATABASE_URL", ""),
		RedisURL:                getenv("REDIS_URL", ""),
		RedisSentinelAddrs:      getenvList("REDIS_SENTINEL_ADDRS"),
		RedisSentinelMaster:     strings.TrimSpace(getenv("REDIS_SENTINEL_MASTER", "")),
		RedisPassword:           getenv("REDIS_PASSWORD", ""),
		RedisSentinelPassword:   getenv("REDIS_SENTINEL_PASSWORD", ""),
		RedisDB:                 clampInt(getenvInt("REDIS_DB", 0), 0, 1024),

		WidgetTokenSecret:     getenv("WIDGET_TOKEN_SECRET", "dev-insecure-widget-secret-change-me-please"),
		WidgetTokenTTLSeconds: getenvInt("WIDGET_TOKEN_TTL_SECONDS", 1800),
		WidgetStaticDir:       getenv("WIDGET_STATIC_DIR", "/app/widget"),
		JWTSecret:             getenv("JWT_SECRET", "dev-insecure-jwt-secret-change-me-please"),
		InternalAPISecret:     getenv("INTERNAL_API_SECRET", ""),
		HistoryMaxMessages:    getenvInt("HISTORY_MAX_MESSAGES", 16),

		MetricsAddr:      getenv("METRICS_ADDR", "127.0.0.1:9090"),
		MetricsToken:     getenv("METRICS_TOKEN", ""),
		ChatMaxBodyBytes: int64(clampInt(getenvInt("CHAT_MAX_BODY_BYTES", DefaultChatMaxBodyBytes), 1024, 64<<20)),
		StreamReasoning:  getenvBool("STREAM_REASONING", false),

		ShutdownDrainSeconds:    clampInt(getenvInt("EDGE_SHUTDOWN_DRAIN_SECONDS", 25), 0, 600),
		ShutdownDelaySeconds:    clampInt(getenvInt("EDGE_SHUTDOWN_DELAY_SECONDS", 0), 0, 300),
		TerminationGraceSeconds: clampInt(getenvInt("EDGE_TERMINATION_GRACE_SECONDS", 30), 1, 3600),

		RateLimitEnabled:                    getenvBool("RATE_LIMIT_ENABLED", true),
		RateLimitChatUserPerMinute:          clampInt(getenvInt("RATE_LIMIT_CHAT_USER_PER_MINUTE", 30), 0, 100000),
		RateLimitChatWidgetSessionPerMinute: clampInt(getenvInt("RATE_LIMIT_CHAT_WIDGET_SESSION_PER_MINUTE", 10), 0, 100000),
		RateLimitChatWidgetIPPerMinute:      clampInt(getenvInt("RATE_LIMIT_CHAT_WIDGET_IP_PER_MINUTE", 30), 0, 100000),
		RateLimitWidgetTokenPerMinute:       clampInt(getenvInt("RATE_LIMIT_WIDGET_TOKEN_PER_MINUTE", 10), 0, 100000),
		RateLimitWidgetTokenIPPerMinute:     clampInt(getenvInt("RATE_LIMIT_WIDGET_TOKEN_IP_PER_MINUTE", 30), 0, 100000),
		HTTPBodyReadTimeoutSeconds:          clampInt(getenvInt("HTTP_BODY_READ_TIMEOUT_SECONDS", 30), 1, 600),
		TrustedProxyCIDRs:                   getenvPrefixes("TRUSTED_PROXY_CIDRS"),

		RetrieveCandidateK:            getenvInt("RETRIEVE_CANDIDATE_K", 80),
		RetrieveContextK:              getenvInt("RETRIEVE_CONTEXT_K", 12),
		RetrieveMaxChunksPerDocument:  clampInt(getenvInt("RETRIEVE_MAX_CHUNKS_PER_DOCUMENT", 3), 0, 100),
		RetrieveLowConfidenceScore:    float32(getenvFloat("RETRIEVE_LOW_CONFIDENCE_SCORE", 0)),
		RerankEnabled:                 getenvBool("RERANK_ENABLED", true),
		RerankCandidateK:              clampInt(getenvInt("RERANK_CANDIDATE_K", 24), 0, 1000),
		PersonalizationEnabled:        getenvBool("PERSONALIZATION_ENABLED", true),
		WebSearchEnabled:              getenvBool("WEB_SEARCH_ENABLED", false),
		WidgetWebSearchEnabled:        getenvBool("WIDGET_WEB_SEARCH_ENABLED", false),
		BraveAPIKey:                   getenv("BRAVE_API_KEY", ""),
		WebSearchTopN:                 getenvInt("WEB_SEARCH_TOP_N", 10),
		WebSearchReadEnabled:          getenvBool("WEB_SEARCH_READ_ENABLED", true),
		WebSearchReadTopN:             getenvInt("WEB_SEARCH_READ_TOP_N", 8),
		WebSearchFetchConcurrency:     getenvInt("WEB_SEARCH_FETCH_CONCURRENCY", 4),
		WebSearchFetchTimeoutSeconds:  getenvInt("WEB_SEARCH_FETCH_TIMEOUT_SECONDS", 5),
		WebSearchMaxBodyBytes:         int64(getenvInt("WEB_SEARCH_MAX_BODY_BYTES", 1500000)),
		WebSearchCountry:              getenv("WEB_SEARCH_COUNTRY", "TR"),
		WebSearchLang:                 getenv("WEB_SEARCH_LANG", "auto"),
		DeepSearchMaxQueries:          getenvInt("DEEP_SEARCH_MAX_QUERIES", 6),
		DeepSearchTopN:                getenvInt("DEEP_SEARCH_TOP_N", 10),
		DeepSearchMaxResults:          getenvInt("DEEP_SEARCH_MAX_RESULTS", 50),
		DeepSearchParallelism:         clampInt(getenvInt("DEEP_SEARCH_PARALLELISM", 2), 1, 16),
		DeepSearchReadTopN:            getenvInt("DEEP_SEARCH_READ_TOP_N", 30),
		DeepSearchEvidenceTopK:        getenvInt("DEEP_SEARCH_EVIDENCE_TOP_K", 20),
		DeepSearchTotalTimeoutSeconds: getenvInt("DEEP_SEARCH_TOTAL_TIMEOUT_SECONDS", 45),
		DeepSearchFollowupRounds:      getenvInt("DEEP_SEARCH_FOLLOWUP_ROUNDS", 1),
		VisionModels:                  getenvSet("VISION_MODELS", ""),
		ToolModels:                    getenvSet("TOOL_MODELS", "gpt-oss-120b"),
		ReasoningModels:               getenvSet("REASONING_MODELS", "gpt-oss-120b"),
		MemoryEnabled:                 getenvBool("MEMORY_ENABLED", true),
		MemoryMaxConcurrency:          clampInt(getenvInt("MEMORY_MAX_CONCURRENCY", 8), 1, 128),
		MemoryJobTimeoutSeconds:       clampInt(getenvInt("MEMORY_JOB_TIMEOUT_SECONDS", 30), 1, 300),

		MCPEnabled:         getenvBool("MCP_ENABLED", false),
		MCPAtlassianURL:    getenv("MCP_ATLASSIAN_URL", "http://mcp-atlassian:9000/mcp"),
		MCPMaxIterations:   clampInt(getenvInt("MCP_MAX_ITERATIONS", 4), 1, 8),
		MCPAllowWriteTools: getenvBool("MCP_ALLOW_WRITE_TOOLS", false),

		AgentUnifiedLoop:   getenvBool("AGENT_UNIFIED_LOOP", false),
		HybridContextMode:  getenvEnum("HYBRID_CONTEXT_MODE", "best", sanitizeHybridContextMode),
		AgentMaxIterations: clampInt(getenvInt("AGENT_MAX_ITERATIONS", getenvInt("MCP_MAX_ITERATIONS", 4)), 1, 8),
	}
	rawProfiles := strings.TrimSpace(os.Getenv("LLM_MODEL_PROFILES_JSON"))
	if rawProfiles != "" {
		cfg.ModelRegistryExplicit = true
		profiles, err := parseModelProfiles(rawProfiles, cfg)
		if err != nil {
			cfg.ModelProfilesError = err.Error()
		} else {
			cfg.ModelProfiles = profiles
		}
	}
	return cfg
}

func parseModelProfiles(raw string, cfg Config) ([]ModelProfile, error) {
	var profiles []ModelProfile
	if err := json.Unmarshal([]byte(raw), &profiles); err != nil {
		return nil, fmt.Errorf("decode LLM_MODEL_PROFILES_JSON: %w", err)
	}
	if len(profiles) == 0 {
		return nil, fmt.Errorf("LLM_MODEL_PROFILES_JSON must contain at least one model")
	}

	seenModels := make(map[string]bool, len(profiles))
	type providerConfig struct {
		baseURL               string
		apiKeyEnv             string
		maxConcurrency        int
		responseHeaderTimeout int
	}
	providers := make(map[string]providerConfig)
	allowedCapabilities := map[string]bool{
		CapabilityReasoning: true,
		CapabilityTools:     true,
		CapabilityVision:    true,
	}

	for i := range profiles {
		profile := &profiles[i]
		profile.ID = strings.TrimSpace(profile.ID)
		profile.Provider = strings.TrimSpace(profile.Provider)
		profile.BaseURL = strings.TrimRight(strings.TrimSpace(profile.BaseURL), "/")
		profile.APIKeyEnv = strings.TrimSpace(profile.APIKeyEnv)
		profile.UpstreamModel = strings.TrimSpace(profile.UpstreamModel)
		if profile.UpstreamModel == "" {
			profile.UpstreamModel = profile.ID
		}
		if profile.MaxConcurrency == 0 {
			profile.MaxConcurrency = cfg.ChatMaxConcurrency
		}
		if profile.MaxTokens == 0 {
			profile.MaxTokens = cfg.ChatMaxTokens
		}
		if profile.ResponseHeaderTimeoutSeconds == 0 {
			profile.ResponseHeaderTimeoutSeconds = cfg.LLMResponseHeaderTimeoutSeconds
		}

		if profile.ID == "" || len(profile.ID) > 200 {
			return nil, fmt.Errorf("model profile %d has an invalid id", i)
		}
		if seenModels[profile.ID] {
			return nil, fmt.Errorf("duplicate model profile id %q", profile.ID)
		}
		seenModels[profile.ID] = true
		if profile.Provider == "" || len(profile.Provider) > 100 {
			return nil, fmt.Errorf("model %q has an invalid provider", profile.ID)
		}
		parsedURL, err := url.Parse(profile.BaseURL)
		if err != nil || parsedURL.Host == "" ||
			(parsedURL.Scheme != "http" && parsedURL.Scheme != "https") ||
			parsedURL.User != nil || parsedURL.RawQuery != "" || parsedURL.Fragment != "" {
			return nil, fmt.Errorf("model %q has an invalid base_url", profile.ID)
		}
		if profile.APIKeyEnv != "" && !envNamePattern.MatchString(profile.APIKeyEnv) {
			return nil, fmt.Errorf("model %q has an invalid api_key_env", profile.ID)
		}
		if profile.UpstreamModel == "" || len(profile.UpstreamModel) > 300 {
			return nil, fmt.Errorf("model %q has an invalid upstream_model", profile.ID)
		}
		if profile.MaxConcurrency < 1 || profile.MaxConcurrency > 4096 {
			return nil, fmt.Errorf("model %q max_concurrency must be in [1,4096]", profile.ID)
		}
		if profile.MaxTokens < 1 || profile.MaxTokens > 1_000_000 {
			return nil, fmt.Errorf("model %q max_tokens must be in [1,1000000]", profile.ID)
		}
		if profile.ResponseHeaderTimeoutSeconds < 5 || profile.ResponseHeaderTimeoutSeconds > 900 {
			return nil, fmt.Errorf("model %q response_header_timeout_seconds must be in [5,900]", profile.ID)
		}

		normalizedCaps := make([]string, 0, len(profile.Capabilities))
		seenCaps := map[string]bool{}
		for _, rawCapability := range profile.Capabilities {
			capability := strings.ToLower(strings.TrimSpace(rawCapability))
			if !allowedCapabilities[capability] {
				return nil, fmt.Errorf(
					"model %q has unsupported capability %q",
					profile.ID,
					rawCapability,
				)
			}
			if !seenCaps[capability] {
				seenCaps[capability] = true
				normalizedCaps = append(normalizedCaps, capability)
			}
		}
		slices.Sort(normalizedCaps)
		profile.Capabilities = normalizedCaps
		if profile.APIKeyEnv != "" {
			profile.APIKey = os.Getenv(profile.APIKeyEnv)
			if profile.APIKey == "" {
				return nil, fmt.Errorf(
					"model %q references unset or empty api_key_env %q",
					profile.ID,
					profile.APIKeyEnv,
				)
			}
		}

		currentProvider := providerConfig{
			baseURL:        profile.BaseURL,
			apiKeyEnv:      profile.APIKeyEnv,
			maxConcurrency: profile.MaxConcurrency,

			responseHeaderTimeout: profile.ResponseHeaderTimeoutSeconds,
		}
		if existing, ok := providers[profile.Provider]; ok && existing != currentProvider {
			return nil, fmt.Errorf(
				"provider %q has conflicting endpoint/key/concurrency/response_header_timeout_seconds settings",
				profile.Provider,
			)
		}
		providers[profile.Provider] = currentProvider
	}
	if !seenModels[cfg.ChatModel] {
		return nil, fmt.Errorf(
			"LLMAAS_CHAT_MODEL %q is not present in LLM_MODEL_PROFILES_JSON",
			cfg.ChatModel,
		)
	}
	return profiles, nil
}

// sanitizeHybridContextMode returns v if it is one of the allowed grounding
// modes (best|web-only|all), else "" so getenvEnum falls back to the default.
func sanitizeHybridContextMode(v string) string {
	switch v {
	case "best", "web-only", "all":
		return v
	default:
		return ""
	}
}

// clampInt bounds n to [lo, hi].
func clampInt(n, lo, hi int) int {
	if n < lo {
		return lo
	}
	if n > hi {
		return hi
	}
	return n
}

// IsDevelopment reports whether RAGGIE_ENV names a development/test
// deployment, the only environments allowed to run with default secrets.
func (c Config) IsDevelopment() bool {
	switch c.Env {
	case "development", "dev", "local", "test", "testing":
		return true
	default:
		return false
	}
}

// Validate enforces the production boot policy: outside development
// DATABASE_URL is required (chat authorization depends on it) and every
// shared secret must be set, must not be a shipped placeholder and must be at
// least minSecretBytes long. Optional secrets are checked only when set. The
// error names the offending variables (never their values) and how to fix it.
func (c Config) Validate() error {
	// Structural misconfiguration fails in every environment.
	if (len(c.RedisSentinelAddrs) > 0) != (c.RedisSentinelMaster != "") {
		return fmt.Errorf("REDIS_SENTINEL_ADDRS and REDIS_SENTINEL_MASTER must be set together " +
			"(or both left empty to use REDIS_URL)")
	}
	if c.IsDevelopment() {
		return nil
	}
	if strings.TrimSpace(c.DatabaseURL) == "" {
		return fmt.Errorf("DATABASE_URL is required (RAGGIE_ENV=%q is treated as production): the edge resolves chat "+
			"authorization from Postgres and refuses chat without it; set DATABASE_URL, or RAGGIE_ENV=development for local use only",
			c.Env)
	}
	secrets := []struct {
		name, value string
		optional    bool
	}{
		{"JWT_SECRET", c.JWTSecret, false},
		{"WIDGET_TOKEN_SECRET", c.WidgetTokenSecret, false},
		{"INTERNAL_API_SECRET", c.InternalAPISecret, true},
		{"METRICS_TOKEN", c.MetricsToken, true},
		{"QDRANT_API_KEY", c.QdrantAPIKey, true},
	}
	var problems []string
	for _, s := range secrets {
		if s.optional && s.value == "" {
			continue
		}
		if reason := weakSecretReason(s.value); reason != "" {
			problems = append(problems, s.name+" "+reason)
		}
	}
	if len(problems) == 0 {
		return nil
	}
	return fmt.Errorf(
		"refusing to start with insecure secrets (RAGGIE_ENV=%q is treated as production): %s; "+
			"generate each with `openssl rand -hex 32`, or set RAGGIE_ENV=development for local use only",
		c.Env, strings.Join(problems, "; "),
	)
}

func weakSecretReason(v string) string {
	lower := strings.ToLower(strings.TrimSpace(v))
	switch {
	case lower == "":
		return "is empty"
	case knownDefaultSecrets[lower]:
		return "is a known default placeholder"
	case strings.Contains(lower, "change-me") || strings.Contains(lower, "changeme") ||
		strings.Contains(lower, "dev-insecure"):
		return "contains a placeholder marker"
	case len(v) < minSecretBytes:
		return fmt.Sprintf("is shorter than %d bytes", minSecretBytes)
	default:
		return ""
	}
}

// ShutdownTailSeconds is the fixed budget after the drain window: forced-cancel
// grace plus listener/background shutdown.
const ShutdownTailSeconds = 3

// ShutdownBudgetWarning returns a non-empty warning when delay + drain + tail
// does not fit strictly inside the termination grace period (the process would
// be SIGKILLed mid-drain).
func (c Config) ShutdownBudgetWarning() string {
	total := c.ShutdownDelaySeconds + c.ShutdownDrainSeconds + ShutdownTailSeconds
	if total < c.TerminationGraceSeconds {
		return ""
	}
	return fmt.Sprintf(
		"shutdown budget %ds (EDGE_SHUTDOWN_DELAY_SECONDS=%d + EDGE_SHUTDOWN_DRAIN_SECONDS=%d + %ds tail) "+
			"does not fit EDGE_TERMINATION_GRACE_SECONDS=%d; streams may be killed without a reconnect event",
		total, c.ShutdownDelaySeconds, c.ShutdownDrainSeconds, ShutdownTailSeconds, c.TerminationGraceSeconds,
	)
}

// getenvPrefixes parses a comma-separated list of CIDRs or bare IPs. Invalid
// entries are dropped (a typo must never widen trust).
func getenvPrefixes(key string) []netip.Prefix {
	var out []netip.Prefix
	for _, part := range strings.Split(os.Getenv(key), ",") {
		part = strings.TrimSpace(part)
		if part == "" {
			continue
		}
		if p, err := netip.ParsePrefix(part); err == nil {
			out = append(out, p.Masked())
			continue
		}
		if a, err := netip.ParseAddr(part); err == nil {
			a = a.Unmap()
			out = append(out, netip.PrefixFrom(a, a.BitLen()))
		}
	}
	return out
}

func defaultLocale() locale.Locale {
	for _, key := range []string{"DEFAULT_LOCALE", "NEXT_PUBLIC_DEFAULT_LOCALE"} {
		if v := strings.TrimSpace(os.Getenv(key)); v != "" {
			if l, ok := locale.Parse(v); ok {
				return l
			}
			return locale.EN
		}
	}
	return locale.EN
}

// defaultTimezone returns DEFAULT_TIMEZONE when it is a loadable IANA zone, else
// "UTC". The control plane refuses to boot on an invalid value, so the fallback
// only matters when the edge runs on its own.
func defaultTimezone() string {
	if v := strings.TrimSpace(os.Getenv("DEFAULT_TIMEZONE")); v != "" {
		if _, err := time.LoadLocation(v); err == nil {
			return v
		}
	}
	return "UTC"
}

// getenvList parses a comma-separated env var into a trimmed list (empties dropped).
func getenvList(key string) []string {
	var out []string
	for _, part := range strings.Split(os.Getenv(key), ",") {
		if p := strings.TrimSpace(part); p != "" {
			out = append(out, p)
		}
	}
	return out
}

// getenvSet parses a comma-separated env var into a set (trimmed, empties dropped).
func getenvSet(key, def string) map[string]bool {
	out := map[string]bool{}
	for _, part := range strings.Split(getenv(key, def), ",") {
		if p := strings.TrimSpace(part); p != "" {
			out[p] = true
		}
	}
	return out
}

// SlogLevel maps the configured log level string to an slog.Level.
func (c Config) SlogLevel() slog.Level {
	switch c.LogLevel {
	case "debug":
		return slog.LevelDebug
	case "warn":
		return slog.LevelWarn
	case "error":
		return slog.LevelError
	default:
		return slog.LevelInfo
	}
}

func getenv(key, def string) string {
	if v, ok := os.LookupEnv(key); ok && v != "" {
		return v
	}
	return def
}

func getenvInt(key string, def int) int {
	if v, ok := os.LookupEnv(key); ok && v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			return n
		}
	}
	return def
}

func getenvFloat(key string, def float64) float64 {
	if v, ok := os.LookupEnv(key); ok && v != "" {
		if f, err := strconv.ParseFloat(v, 64); err == nil {
			return f
		}
	}
	return def
}

// getenvEnum reads an env var and accepts it only if valid(v) returns a
// non-empty value; otherwise it falls back to def (so a typo'd value can't
// silently disable or misconfigure the feature).
func getenvEnum(key, def string, valid func(string) string) string {
	if v, ok := os.LookupEnv(key); ok && v != "" {
		if okv := valid(strings.TrimSpace(strings.ToLower(v))); okv != "" {
			return okv
		}
	}
	return def
}

func getenvBool(key string, def bool) bool {
	if v, ok := os.LookupEnv(key); ok && v != "" {
		if b, err := strconv.ParseBool(v); err == nil {
			return b
		}
	}
	return def
}
