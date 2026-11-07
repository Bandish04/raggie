// SPDX-License-Identifier: Apache-2.0

package config

import (
	"strings"
	"testing"
)

func TestLoadRetrievalAndDeepSearchDefaults(t *testing.T) {
	for _, key := range []string{
		"RETRIEVE_CANDIDATE_K",
		"RETRIEVE_CONTEXT_K",
		"RETRIEVE_MAX_CHUNKS_PER_DOCUMENT",
		"RERANK_CANDIDATE_K",
		"DEEP_SEARCH_PARALLELISM",
	} {
		t.Setenv(key, "")
	}

	cfg := Load()
	if cfg.RetrieveCandidateK != 80 || cfg.RetrieveContextK != 12 {
		t.Fatalf(
			"retrieval defaults = candidate:%d context:%d, want 80/12",
			cfg.RetrieveCandidateK,
			cfg.RetrieveContextK,
		)
	}
	if cfg.RetrieveMaxChunksPerDocument != 3 {
		t.Fatalf("per-document default = %d, want 3", cfg.RetrieveMaxChunksPerDocument)
	}
	if cfg.RerankCandidateK != 24 {
		t.Fatalf("rerank candidate default = %d, want 24", cfg.RerankCandidateK)
	}
	if cfg.DeepSearchParallelism != 2 {
		t.Fatalf("deep-search parallelism default = %d, want 2", cfg.DeepSearchParallelism)
	}
}

func TestLoadClampsEvidenceConcurrencyAndDiversity(t *testing.T) {
	t.Setenv("DEEP_SEARCH_PARALLELISM", "999")
	t.Setenv("RETRIEVE_MAX_CHUNKS_PER_DOCUMENT", "-5")
	t.Setenv("RERANK_CANDIDATE_K", "5000")

	cfg := Load()
	if cfg.DeepSearchParallelism != 16 {
		t.Fatalf("deep-search parallelism = %d, want clamp 16", cfg.DeepSearchParallelism)
	}
	if cfg.RetrieveMaxChunksPerDocument != 0 {
		t.Fatalf("per-document cap = %d, want disabled clamp 0", cfg.RetrieveMaxChunksPerDocument)
	}
	if cfg.RerankCandidateK != 1000 {
		t.Fatalf("rerank candidate cap = %d, want clamp 1000", cfg.RerankCandidateK)
	}
}

func TestLoadExplicitModelProfiles(t *testing.T) {
	t.Setenv("LLMAAS_CHAT_MODEL", "local-general")
	t.Setenv("LOCAL_LLM_KEY", "local-secret")
	t.Setenv("LLM_MODEL_PROFILES_JSON", `[
		{
			"id":"local-general",
			"provider":"ollama",
			"base_url":"http://ollama:11434/v1/",
			"api_key_env":"LOCAL_LLM_KEY",
			"upstream_model":"qwen3:14b",
			"max_concurrency":3,
			"max_tokens":4096,
			"capabilities":["tools","reasoning","tools"]
		},
		{
			"id":"managed-vision",
			"provider":"managed",
			"base_url":"https://llm.example/v1",
			"upstream_model":"vision-1",
			"capabilities":["vision"]
		}
	]`)

	cfg := Load()
	if cfg.ModelProfilesError != "" {
		t.Fatalf("unexpected profile error: %s", cfg.ModelProfilesError)
	}
	if !cfg.ModelRegistryExplicit || len(cfg.ModelProfiles) != 2 {
		t.Fatalf("explicit registry not loaded: %+v", cfg.ModelProfiles)
	}
	local, ok := cfg.ModelProfile("local-general")
	if !ok || local.BaseURL != "http://ollama:11434/v1" ||
		local.APIKey != "local-secret" || local.UpstreamModel != "qwen3:14b" {
		t.Fatalf("unexpected local profile: %+v", local)
	}
	if !cfg.SupportsReasoning("local-general") || !cfg.SupportsTools("local-general") {
		t.Fatal("local model capabilities were not loaded")
	}
	if cfg.SupportsVision("local-general") || cfg.ProviderForModel("local-general") != "ollama" {
		t.Fatal("unexpected local model capability/provider")
	}
	if !cfg.SupportsVision("managed-vision") || cfg.HasModel("missing") {
		t.Fatal("explicit registry must expose only configured canonical ids")
	}
}

func TestLoadRejectsInvalidModelProfiles(t *testing.T) {
	tests := map[string]string{ // #nosec G101 -- invalid model-profile fixtures, no credentials
		"malformed": `{`,
		"missing default": `[
			{"id":"other","provider":"p","base_url":"http://localhost:1/v1"}
		]`,
		"duplicate id": `[
			{"id":"default","provider":"p","base_url":"http://localhost:1/v1"},
			{"id":"default","provider":"p","base_url":"http://localhost:1/v1"}
		]`,
		"provider conflict": `[
			{"id":"default","provider":"p","base_url":"http://localhost:1/v1"},
			{"id":"other","provider":"p","base_url":"http://localhost:2/v1"}
		]`,
		"unknown capability": `[
			{"id":"default","provider":"p","base_url":"http://localhost:1/v1","capabilities":["magic"]}
		]`,
		"missing referenced secret": `[
			{"id":"default","provider":"p","base_url":"http://localhost:1/v1","api_key_env":"MISSING_ROUTER_TEST_KEY"}
		]`,
	}
	for name, raw := range tests {
		t.Run(name, func(t *testing.T) {
			t.Setenv("LLMAAS_CHAT_MODEL", "default")
			t.Setenv("LLM_MODEL_PROFILES_JSON", raw)
			t.Setenv("MISSING_ROUTER_TEST_KEY", "")
			cfg := Load()
			if !cfg.ModelRegistryExplicit || strings.TrimSpace(cfg.ModelProfilesError) == "" {
				t.Fatalf("expected boot-fatal profile error, got %+v", cfg)
			}
		})
	}
}

// strongSecret is a 48-byte random-looking value that passes the production
// secret policy.
const strongSecret = "3f9c1a7e5b2d8046e1f7a9c3b5d7e9f1a2c4e6b8d0f2a4c6" // #nosec G101 -- test-only value

func setStrongSecrets(t *testing.T) {
	t.Helper()
	t.Setenv("JWT_SECRET", strongSecret)
	t.Setenv("WIDGET_TOKEN_SECRET", strongSecret+"-w")
	t.Setenv("INTERNAL_API_SECRET", "")
	t.Setenv("METRICS_TOKEN", "")
	t.Setenv("QDRANT_API_KEY", "")
	t.Setenv("DATABASE_URL", "postgresql://raggie@postgres:5432/raggie")
}

func TestValidateAcceptsStrongSecretsInProduction(t *testing.T) {
	setStrongSecrets(t)
	t.Setenv("RAGGIE_ENV", "production")
	if err := Load().Validate(); err != nil {
		t.Fatalf("strong secrets rejected: %v", err)
	}
}

func TestValidateRejectsWeakSecretsOutsideDevelopment(t *testing.T) {
	cases := map[string]struct{ key, value string }{
		"unset jwt uses built-in default":    {"JWT_SECRET", ""},
		"unset widget uses built-in default": {"WIDGET_TOKEN_SECRET", ""},
		"env example placeholder":            {"JWT_SECRET", "change-me-to-a-random-32-byte-min-secret"},
		"contains change-me":                 {"WIDGET_TOKEN_SECRET", "prod-CHANGE-ME-0123456789abcdef0123456789"},
		"too short jwt":                      {"JWT_SECRET", "short-but-random-9f8e7d"},
		"too short internal api secret":      {"INTERNAL_API_SECRET", "s3cr3t"},
		"weak metrics token":                 {"METRICS_TOKEN", "change-me"},
		"weak qdrant api key":                {"QDRANT_API_KEY", "qdrant"},
	}
	for name, tc := range cases {
		for _, env := range []string{"", "production", "staging"} {
			t.Run(name+"/"+env, func(t *testing.T) {
				setStrongSecrets(t)
				t.Setenv("RAGGIE_ENV", env)
				t.Setenv(tc.key, tc.value)
				err := Load().Validate()
				if err == nil {
					t.Fatalf("expected %s=%q to be rejected (RAGGIE_ENV=%q)", tc.key, tc.value, env)
				}
				if !strings.Contains(err.Error(), tc.key) || !strings.Contains(err.Error(), "RAGGIE_ENV") {
					t.Fatalf("error should name the variable and the escape hatch, got: %v", err)
				}
				if tc.value != "" && strings.Contains(err.Error(), tc.value) {
					t.Fatalf("error must not echo the secret value, got: %v", err)
				}
			})
		}
	}
}

func TestValidateAllowsDefaultsInDevelopment(t *testing.T) {
	for _, env := range []string{"development", "dev", "local", "test", "testing", "DEVELOPMENT", "Local"} {
		t.Run(env, func(t *testing.T) {
			t.Setenv("RAGGIE_ENV", env)
			t.Setenv("JWT_SECRET", "")
			t.Setenv("WIDGET_TOKEN_SECRET", "")
			t.Setenv("INTERNAL_API_SECRET", "dev")
			if err := Load().Validate(); err != nil {
				t.Fatalf("development must tolerate default secrets, got %v", err)
			}
		})
	}
}

func TestLoadSecurityDefaults(t *testing.T) {
	for _, key := range []string{
		"RAGGIE_ENV", "STREAM_REASONING", "CHAT_MAX_BODY_BYTES", "METRICS_ADDR",
		"RATE_LIMIT_ENABLED", "RATE_LIMIT_CHAT_USER_PER_MINUTE",
		"RATE_LIMIT_CHAT_WIDGET_SESSION_PER_MINUTE", "RATE_LIMIT_CHAT_WIDGET_IP_PER_MINUTE",
		"RATE_LIMIT_WIDGET_TOKEN_PER_MINUTE", "TRUSTED_PROXY_CIDRS", "MCP_ALLOW_WRITE_TOOLS",
	} {
		t.Setenv(key, "")
	}
	cfg := Load()
	if cfg.Env != "production" || cfg.IsDevelopment() {
		t.Fatalf("unset RAGGIE_ENV must mean production, got %q", cfg.Env)
	}
	if cfg.StreamReasoning {
		t.Fatal("STREAM_REASONING must default to false")
	}
	if cfg.ChatMaxBodyBytes != DefaultChatMaxBodyBytes {
		t.Fatalf("CHAT_MAX_BODY_BYTES default = %d, want %d", cfg.ChatMaxBodyBytes, DefaultChatMaxBodyBytes)
	}
	if cfg.MetricsAddr != "127.0.0.1:9090" {
		t.Fatalf("METRICS_ADDR default = %q", cfg.MetricsAddr)
	}
	if !cfg.RateLimitEnabled || cfg.RateLimitChatUserPerMinute != 30 ||
		cfg.RateLimitChatWidgetSessionPerMinute != 10 || cfg.RateLimitChatWidgetIPPerMinute != 30 ||
		cfg.RateLimitWidgetTokenPerMinute != 10 {
		t.Fatalf("unexpected rate-limit defaults: %+v", cfg)
	}
	if len(cfg.TrustedProxyCIDRs) != 0 || cfg.MCPAllowWriteTools {
		t.Fatalf("unexpected proxy/MCP defaults: %+v %v", cfg.TrustedProxyCIDRs, cfg.MCPAllowWriteTools)
	}
}

func TestLoadParsesTrustedProxyCIDRs(t *testing.T) {
	t.Setenv("TRUSTED_PROXY_CIDRS", "10.0.0.0/8, 192.168.1.10 ,bogus")
	cfg := Load()
	if len(cfg.TrustedProxyCIDRs) != 2 {
		t.Fatalf("trusted proxies = %v, want 2 valid entries (bare IP accepted, junk dropped)", cfg.TrustedProxyCIDRs)
	}
}

func TestLoadRedisSentinelSettings(t *testing.T) {
	t.Setenv("REDIS_SENTINEL_ADDRS", " s0:26379, s1:26379 ,")
	t.Setenv("REDIS_SENTINEL_MASTER", "raggie")
	t.Setenv("REDIS_PASSWORD", "rp")
	t.Setenv("REDIS_SENTINEL_PASSWORD", "sp")
	t.Setenv("REDIS_DB", "1")
	cfg := Load()
	if len(cfg.RedisSentinelAddrs) != 2 || cfg.RedisSentinelAddrs[1] != "s1:26379" ||
		cfg.RedisSentinelMaster != "raggie" || cfg.RedisPassword != "rp" ||
		cfg.RedisSentinelPassword != "sp" || cfg.RedisDB != 1 {
		t.Fatalf("unexpected sentinel config: %+v", cfg)
	}
}

// A half-configured Sentinel setup is a boot error in every environment.
func TestValidateRejectsPartialSentinelConfig(t *testing.T) {
	for _, tc := range []struct{ addrs, master string }{{"s0:26379", ""}, {"", "raggie"}} {
		t.Setenv("RAGGIE_ENV", "development")
		t.Setenv("REDIS_SENTINEL_ADDRS", tc.addrs)
		t.Setenv("REDIS_SENTINEL_MASTER", tc.master)
		err := Load().Validate()
		if err == nil || !strings.Contains(err.Error(), "REDIS_SENTINEL") {
			t.Fatalf("addrs=%q master=%q: expected a sentinel config error, got %v", tc.addrs, tc.master, err)
		}
	}
}

func TestLoadShutdownDrainSeconds(t *testing.T) {
	t.Setenv("EDGE_SHUTDOWN_DRAIN_SECONDS", "")
	if got := Load().ShutdownDrainSeconds; got != 25 {
		t.Fatalf("default drain = %d, want 25", got)
	}
	t.Setenv("EDGE_SHUTDOWN_DRAIN_SECONDS", "9999")
	if got := Load().ShutdownDrainSeconds; got != 600 {
		t.Fatalf("drain must be clamped to 600, got %d", got)
	}
}

func TestShutdownBudget(t *testing.T) {
	for _, key := range []string{"EDGE_SHUTDOWN_DELAY_SECONDS", "EDGE_SHUTDOWN_DRAIN_SECONDS", "EDGE_TERMINATION_GRACE_SECONDS"} {
		t.Setenv(key, "")
	}
	cfg := Load()
	if cfg.ShutdownDelaySeconds != 0 || cfg.TerminationGraceSeconds != 30 {
		t.Fatalf("defaults: delay=%d grace=%d", cfg.ShutdownDelaySeconds, cfg.TerminationGraceSeconds)
	}
	if w := cfg.ShutdownBudgetWarning(); w != "" {
		t.Fatalf("defaults (0+25+3 < 30) must not warn: %s", w)
	}
	cfg.ShutdownDelaySeconds = 5 // 5+25+3 = 33 >= 30
	w := cfg.ShutdownBudgetWarning()
	if !strings.Contains(w, "EDGE_SHUTDOWN_DELAY_SECONDS") || !strings.Contains(w, "33") {
		t.Fatalf("expected an over-budget warning, got %q", w)
	}
	cfg.TerminationGraceSeconds = 40
	if w := cfg.ShutdownBudgetWarning(); w != "" {
		t.Fatalf("5+25+3 < 40 must not warn: %s", w)
	}
}

func TestLoadDefaultLocale(t *testing.T) {
	cases := []struct{ def, public, want string }{
		{"", "", "en"},     // open-source default
		{"", "tr", "tr"},   // shared .env: follow the web's NEXT_PUBLIC_DEFAULT_LOCALE
		{"en", "tr", "en"}, // explicit edge setting wins
		{"tr-TR", "", "tr"},
		{"de", "", "en"}, // unsupported -> English
	}
	for _, tc := range cases {
		t.Setenv("DEFAULT_LOCALE", tc.def)
		t.Setenv("NEXT_PUBLIC_DEFAULT_LOCALE", tc.public)
		if got := string(Load().DefaultLocale); got != tc.want {
			t.Errorf("DEFAULT_LOCALE=%q NEXT_PUBLIC_DEFAULT_LOCALE=%q -> %q, want %q", tc.def, tc.public, got, tc.want)
		}
	}
}

func TestLoadEmbeddingsGatewayTimeouts(t *testing.T) {
	t.Setenv("EMBED_QUERY_TIMEOUT_MS", "")
	t.Setenv("RERANK_TIMEOUT_MS", "")
	cfg := Load()
	if cfg.EmbedQueryTimeoutMS != 8000 || cfg.RerankTimeoutMS != 5000 {
		t.Fatalf("timeout defaults = query:%d rerank:%d, want 8000/5000", cfg.EmbedQueryTimeoutMS, cfg.RerankTimeoutMS)
	}

	t.Setenv("EMBED_QUERY_TIMEOUT_MS", "2500")
	t.Setenv("RERANK_TIMEOUT_MS", "1500")
	cfg = Load()
	if cfg.EmbedQueryTimeoutMS != 2500 || cfg.RerankTimeoutMS != 1500 {
		t.Fatalf("timeouts = query:%d rerank:%d, want 2500/1500", cfg.EmbedQueryTimeoutMS, cfg.RerankTimeoutMS)
	}

	t.Setenv("EMBED_QUERY_TIMEOUT_MS", "1")
	t.Setenv("RERANK_TIMEOUT_MS", "99999999")
	cfg = Load()
	if cfg.EmbedQueryTimeoutMS != 100 || cfg.RerankTimeoutMS != 120000 {
		t.Fatalf("clamped timeouts = query:%d rerank:%d, want 100/120000", cfg.EmbedQueryTimeoutMS, cfg.RerankTimeoutMS)
	}
}

// Without a database the edge cannot verify who is chatting (workspace type,
// membership, token revocation), so outside development it must not boot.
func TestValidateRequiresDatabaseURLOutsideDevelopment(t *testing.T) {
	for _, env := range []string{"", "production", "staging"} {
		t.Run(env, func(t *testing.T) {
			setStrongSecrets(t)
			t.Setenv("RAGGIE_ENV", env)
			t.Setenv("DATABASE_URL", "")
			err := Load().Validate()
			if err == nil || !strings.Contains(err.Error(), "DATABASE_URL") || !strings.Contains(err.Error(), "RAGGIE_ENV") {
				t.Fatalf("RAGGIE_ENV=%q without DATABASE_URL: err = %v", env, err)
			}
		})
	}
	t.Setenv("RAGGIE_ENV", "development")
	t.Setenv("DATABASE_URL", "")
	if err := Load().Validate(); err != nil {
		t.Fatalf("development without a database must still boot (chat then refuses): %v", err)
	}
}

func TestLoadLLMResponseHeaderTimeout(t *testing.T) {
	for raw, want := range map[string]int{"": 60, "300": 300, "1": 5, "5000": 900, "garbage": 60} {
		t.Setenv("LLMAAS_RESPONSE_HEADER_TIMEOUT_SECONDS", raw)
		if got := Load().LLMResponseHeaderTimeoutSeconds; got != want {
			t.Errorf("LLMAAS_RESPONSE_HEADER_TIMEOUT_SECONDS=%q → %d, want %d", raw, got, want)
		}
	}
}

// Profiles inherit the global header timeout unless they set their own; the
// override is bounded like the global knob and must agree within a provider.
func TestModelProfileResponseHeaderTimeout(t *testing.T) {
	t.Setenv("LLMAAS_CHAT_MODEL", "local")
	t.Setenv("LLMAAS_RESPONSE_HEADER_TIMEOUT_SECONDS", "90")
	t.Setenv("LLM_MODEL_PROFILES_JSON", `[
		{"id":"local","provider":"ollama","base_url":"http://ollama:11434/v1","response_header_timeout_seconds":300},
		{"id":"managed","provider":"managed","base_url":"https://llm.example/v1"}
	]`)
	cfg := Load()
	if cfg.ModelProfilesError != "" {
		t.Fatal(cfg.ModelProfilesError)
	}
	local, _ := cfg.ModelProfile("local")
	managed, _ := cfg.ModelProfile("managed")
	if local.ResponseHeaderTimeoutSeconds != 300 || managed.ResponseHeaderTimeoutSeconds != 90 {
		t.Fatalf("header timeouts = local %d, managed %d; want 300 and the global 90",
			local.ResponseHeaderTimeoutSeconds, managed.ResponseHeaderTimeoutSeconds)
	}

	for name, profiles := range map[string]string{
		"too short": `[{"id":"local","provider":"ollama","base_url":"http://o:1/v1","response_header_timeout_seconds":4}]`,
		"too long":  `[{"id":"local","provider":"ollama","base_url":"http://o:1/v1","response_header_timeout_seconds":901}]`,
		"conflict": `[{"id":"local","provider":"ollama","base_url":"http://o:1/v1","response_header_timeout_seconds":300},
		              {"id":"other","provider":"ollama","base_url":"http://o:1/v1","response_header_timeout_seconds":60}]`,
	} {
		t.Setenv("LLM_MODEL_PROFILES_JSON", profiles)
		if err := Load().ModelProfilesError; !strings.Contains(err, "response_header_timeout_seconds") && !strings.Contains(err, "conflicting") {
			t.Errorf("%s: profile error = %q", name, err)
		}
	}
}

func TestLoadDefaultTimezone(t *testing.T) {
	for _, tc := range []struct{ env, want string }{
		{"", "UTC"},
		{"Europe/Istanbul", "Europe/Istanbul"},
		{"  America/New_York ", "America/New_York"},
		{"Not/AZone", "UTC"},
	} {
		t.Setenv("DEFAULT_TIMEZONE", tc.env)
		if got := Load().DefaultTimezone; got != tc.want {
			t.Errorf("DEFAULT_TIMEZONE=%q: got %q, want %q", tc.env, got, tc.want)
		}
	}
}

func TestLoadEdgeMaxSSEConnections(t *testing.T) {
	for raw, want := range map[string]int{"": 12500, "0": 0, "200": 200, "-5": 0, "garbage": 12500} {
		t.Setenv("EDGE_MAX_SSE_CONNECTIONS", raw)
		if got := Load().EdgeMaxSSEConnections; got != want {
			t.Errorf("EDGE_MAX_SSE_CONNECTIONS=%q → %d, want %d", raw, got, want)
		}
	}
}

func TestLoadWidgetWebSearchDefaultsOff(t *testing.T) {
	t.Setenv("WIDGET_WEB_SEARCH_ENABLED", "")
	if Load().WidgetWebSearchEnabled {
		t.Fatal("the widget must not trigger web search unless explicitly enabled")
	}
	t.Setenv("WIDGET_WEB_SEARCH_ENABLED", "true")
	if !Load().WidgetWebSearchEnabled {
		t.Fatal("WIDGET_WEB_SEARCH_ENABLED=true was ignored")
	}
}

func TestLoadWidgetTokenIPLimitAndBodyReadTimeout(t *testing.T) {
	t.Setenv("RATE_LIMIT_WIDGET_TOKEN_IP_PER_MINUTE", "")
	t.Setenv("HTTP_BODY_READ_TIMEOUT_SECONDS", "")
	if cfg := Load(); cfg.RateLimitWidgetTokenIPPerMinute != 30 || cfg.HTTPBodyReadTimeoutSeconds != 30 {
		t.Fatalf("defaults: ip=%d body=%d, want 30 and 30", cfg.RateLimitWidgetTokenIPPerMinute, cfg.HTTPBodyReadTimeoutSeconds)
	}
	t.Setenv("HTTP_BODY_READ_TIMEOUT_SECONDS", "0") // a body deadline is always on
	if got := Load().HTTPBodyReadTimeoutSeconds; got != 1 {
		t.Fatalf("HTTP_BODY_READ_TIMEOUT_SECONDS=0 → %d, want the 1 s floor", got)
	}
}
