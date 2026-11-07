// SPDX-License-Identifier: Apache-2.0

// Command edge is the Raggie real-time Chat/RAG edge service.
//
// It owns the synchronous RAG hot path: SSE streaming, retrieval orchestration,
// Qdrant search and context assembly. This file is the process entrypoint:
// config load, logging, server start and graceful drain.
package main

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/alicangunduz/raggie/services/edge/internal/bus"
	"github.com/alicangunduz/raggie/services/edge/internal/config"
	"github.com/alicangunduz/raggie/services/edge/internal/httpserver"
	"github.com/alicangunduz/raggie/services/edge/internal/llm"
	"github.com/alicangunduz/raggie/services/edge/internal/mcp"
	"github.com/alicangunduz/raggie/services/edge/internal/outboundhttp"
	"github.com/alicangunduz/raggie/services/edge/internal/ports"
	"github.com/alicangunduz/raggie/services/edge/internal/rag"
	"github.com/alicangunduz/raggie/services/edge/internal/ratelimit"
	"github.com/alicangunduz/raggie/services/edge/internal/redisconn"
	"github.com/alicangunduz/raggie/services/edge/internal/store"
	"github.com/alicangunduz/raggie/services/edge/internal/vectorstore"
	"github.com/alicangunduz/raggie/services/edge/internal/websearch"
)

// newEmbeddingsClients builds the embeddings-gateway clients. Both authenticate
// with INTERNAL_API_SECRET (required by the gateway in cloud mode); the LLM
// provider key is never sent to the gateway. The reranker is nil unless
// RERANK_ENABLED.
func newEmbeddingsClients(cfg config.Config, logger *slog.Logger) (*llm.QueryEmbedder, *llm.Reranker) {
	queryEmbedder := llm.NewQueryEmbedder(
		cfg.EmbeddingsBaseURL,
		cfg.InternalAPISecret,
		time.Duration(cfg.EmbedQueryTimeoutMS)*time.Millisecond,
		cfg.EmbedMaxConcurrency,
	).WithLogger(logger)
	if !cfg.RerankEnabled {
		return queryEmbedder, nil
	}
	reranker := llm.NewReranker(
		cfg.EmbeddingsBaseURL,
		cfg.InternalAPISecret,
		time.Duration(cfg.RerankTimeoutMS)*time.Millisecond,
		cfg.EmbedMaxConcurrency,
	).WithLogger(logger)
	return queryEmbedder, reranker
}

// loadConfig reads the environment and rejects a configuration the edge must
// not start with (insecure production secrets, a broken model registry).
func loadConfig() (config.Config, error) {
	cfg := config.Load()
	if err := cfg.Validate(); err != nil {
		return cfg, fmt.Errorf("invalid configuration: %w", err)
	}
	if cfg.ModelProfilesError != "" {
		return cfg, fmt.Errorf("invalid model provider registry: %s", cfg.ModelProfilesError)
	}
	return cfg, nil
}

// newVectorStore builds the Qdrant client, authenticated with QDRANT_API_KEY
// when one is set.
func newVectorStore(cfg config.Config) *vectorstore.QdrantStore {
	return vectorstore.NewQdrantStore(cfg.QdrantURL).WithAPIKey(cfg.QdrantAPIKey)
}

func main() {
	cfg, cfgErr := loadConfig()

	logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: cfg.SlogLevel()}))
	slog.SetDefault(logger)
	if cfgErr != nil {
		logger.Error("refusing to start", "err", cfgErr)
		os.Exit(1)
	}

	// Retrieval + chat collaborators, all behind interfaces so providers can be
	// swapped without touching the RAG core.
	// The query embedder returns dense + sparse vectors (and the collection to
	// search) for hybrid retrieval; the reranker is optional and fail-open.
	queryEmbedder, rerankClient := newEmbeddingsClients(cfg, logger)
	go func() {
		// Log the gateway's embedding profile (model, dim, collection, egress)
		// without delaying startup; readiness retries lazily if it is not up yet.
		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		_, _ = queryEmbedder.RefreshInfo(ctx)
	}()
	vectorStore := newVectorStore(cfg)
	var (
		chat      ports.ChatProvider
		models    ports.ModelLister
		chatReady httpserver.ReadinessPort
	)
	if cfg.ModelRegistryExplicit {
		router, err := llm.NewChatRouter(cfg.ModelProfiles, cfg.ChatModel)
		if err != nil {
			logger.Error("build model provider router", "err", err)
			os.Exit(1)
		}
		chat, models, chatReady = router, router, router
		logger.Info(
			"provider-aware model routing enabled",
			"models", len(cfg.ModelProfiles),
		)
	} else {
		provider := llm.NewChatProvider(
			cfg.LLMaaSBaseURL,
			cfg.LLMaaSAPIKey,
			cfg.ChatModel,
			cfg.ChatMaxTokens,
			cfg.ChatMaxConcurrency,
		).WithResponseHeaderTimeout(time.Duration(cfg.LLMResponseHeaderTimeoutSeconds) * time.Second)
		chat, models, chatReady = provider, provider, provider
	}

	// Optional retrieval quality boosters. The reranker is fail-open (any error
	// keeps the fused order); the low-confidence hint is off unless tuned.
	ragOpts := []rag.Option{rag.WithLogger(logger)}
	var reranker ports.Reranker
	if rerankClient != nil {
		reranker = rerankClient
		ragOpts = append(ragOpts, rag.WithReranker(reranker))
		if cfg.RerankCandidateK > 0 {
			ragOpts = append(ragOpts, rag.WithRerankCandidateK(cfg.RerankCandidateK))
		}
	}
	if cfg.RetrieveLowConfidenceScore > 0 {
		ragOpts = append(ragOpts, rag.WithLowConfidenceScore(cfg.RetrieveLowConfidenceScore))
	}
	if cfg.RetrieveMaxChunksPerDocument > 0 {
		ragOpts = append(ragOpts, rag.WithMaxChunksPerDocument(cfg.RetrieveMaxChunksPerDocument))
	}
	var background *httpserver.BackgroundJobs
	if cfg.MemoryEnabled {
		background = httpserver.NewBackgroundJobs(
			cfg.MemoryMaxConcurrency,
			time.Duration(cfg.MemoryJobTimeoutSeconds)*time.Second,
			logger,
		)
	}
	drain := httpserver.NewDrainer()
	deps := httpserver.Deps{
		Drain:       drain,
		Streams:     httpserver.NewStreamLimiter(cfg.EdgeMaxSSEConnections),
		RAG:         rag.New(queryEmbedder, vectorStore, ragOpts...),
		Chat:        chat,
		Models:      models,
		WebReranker: reranker,
		Background:  background,
		Readiness: []httpserver.ReadinessCheck{
			{Name: "qdrant", Probe: vectorStore, Required: true},
			{Name: "embeddings", Probe: queryEmbedder, Required: true},
			{Name: "llm", Probe: chatReady, Required: true},
		},
	}

	// Optional persistence + events; their absence degrades gracefully.
	if cfg.DatabaseURL != "" {
		if st, err := store.New(context.Background(), cfg.DatabaseURL); err != nil {
			logger.Error("postgres connect failed", "err", err)
			os.Exit(1)
		} else {
			deps.Store = st
			deps.WSInfo = st // workspace lookups for A4 widget/CORS enforcement
			deps.TokenState = st
			deps.Readiness = append(deps.Readiness, httpserver.ReadinessCheck{
				Name: "postgres", Probe: st, Required: true,
			})
			defer st.Close()
		}
	}
	if deps.WSInfo == nil {
		// Only reachable in development (Validate requires DATABASE_URL elsewhere):
		// nothing can authorize chat, so the chat endpoints refuse with 503.
		logger.Warn("no DATABASE_URL: chat and run-task are disabled (503) because they cannot be authorized")
	}
	// One Redis client (Sentinel failover client or REDIS_URL) shared by the
	// event bus, idempotency keys and the rate limiter.
	if rdb, mode, err := redisconn.New(cfg); err != nil {
		logger.Error("redis configuration invalid; events disabled", "err", err)
	} else if rdb != nil {
		b := bus.NewFromClient(rdb)
		deps.Bus = b
		deps.Readiness = append(deps.Readiness, httpserver.ReadinessCheck{Name: "redis", Probe: b})
		defer b.Close()
		logger.Info("redis configured", "mode", mode, "sentinels", len(cfg.RedisSentinelAddrs))
	}

	// Rate limiting shares the Redis pool; without Redis it is off (logged).
	// The limiter itself fails open on Redis errors.
	if cfg.RateLimitEnabled {
		if deps.Bus != nil {
			deps.RateLimiter = ratelimit.NewRedis(deps.Bus.Redis(), "raggie:rl")
			logger.Info("rate limiting enabled",
				"chat_user_per_min", cfg.RateLimitChatUserPerMinute,
				"chat_widget_session_per_min", cfg.RateLimitChatWidgetSessionPerMinute,
				"chat_widget_ip_per_min", cfg.RateLimitChatWidgetIPPerMinute,
				"widget_token_per_min", cfg.RateLimitWidgetTokenPerMinute,
				"trusted_proxies", len(cfg.TrustedProxyCIDRs))
		} else {
			logger.Warn("rate limiting disabled: no Redis configured (REDIS_URL or REDIS_SENTINEL_*)")
		}
	}

	// Optional web-search fallback (Brave). Only wired when globally enabled AND a
	// key is present; otherwise it stays nil and the chat is documents-only.
	if cfg.WebSearchEnabled && cfg.BraveAPIKey != "" {
		brave := websearch.New(cfg.BraveAPIKey, cfg.ChatMaxConcurrency, cfg.WebSearchTopN)
		deps.Web = brave
		deps.WebResearch = brave
		logger.Info("web search enabled (Brave)")
	}

	// Optional MCP tool-use (Phase 1: Jira READ tools via a self-hosted
	// mcp-atlassian container). GLOBAL kill-switch, default OFF. When enabled the
	// client connects lazily on first use; tools are still gated per-org by a
	// connected `jira` integration. The edge never holds Jira credentials.
	if cfg.MCPEnabled && cfg.MCPAtlassianURL != "" {
		deps.MCP = mcp.New(cfg.MCPAtlassianURL, cfg.MCPMaxIterations).WithLogger(logger)
		logger.Info("mcp tool-use enabled", "url", cfg.MCPAtlassianURL, "max_iterations", cfg.MCPMaxIterations)
	}

	if w := cfg.ShutdownBudgetWarning(); w != "" {
		logger.Warn(w)
	}

	if cfg.AgentUnifiedLoop {
		logger.Info("unified agentic loop enabled",
			"hybrid_context_mode", cfg.HybridContextMode, "agent_max_iterations", cfg.AgentMaxIterations)
	}

	srv := httpserver.New(cfg, logger, deps)

	go func() {
		logger.Info("edge listening", "addr", srv.Addr)
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			logger.Error("server error", "err", err)
			os.Exit(1)
		}
	}()

	// Internal-only metrics listener (never on the public port). A bind failure
	// is logged but does not take the chat surface down.
	metricsSrv := httpserver.NewMetricsServer(cfg, logger, deps)
	go func() {
		logger.Info("metrics listening", "addr", metricsSrv.Addr, "token_required", cfg.MetricsToken != "")
		if err := metricsSrv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			logger.Error("metrics server error", "err", err)
		}
	}()

	// Wait for SIGINT/SIGTERM, then run the graceful shutdown sequence below.
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	<-ctx.Done()

	// Graceful shutdown, sized to fit the orchestrator's grace period
	// (delay + drain + ShutdownTailSeconds < EDGE_TERMINATION_GRACE_SECONDS):
	//  0. fail readiness but keep serving for EDGE_SHUTDOWN_DELAY_SECONDS, so
	//     endpoint removal propagates before anything is refused;
	//  1. refuse new SSE streams (503 + Retry-After) while listeners stay open;
	//  2. let in-flight streams finish within EDGE_SHUTDOWN_DRAIN_SECONDS;
	//  3. cancel stragglers — each ends with an SSE "reconnect" event and its
	//     partial answer persisted;
	//  4. close listeners and drain the remaining short requests/background jobs.
	// A second signal skips the remaining waits (stragglers still get reconnect).
	const forcedGrace, tailBudget = 1 * time.Second, 2 * time.Second
	logger.Info("shutdown signal received")
	hurry, stopHurry := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	drain.Shutdown(hurry, httpserver.ShutdownPlan{
		Delay:       time.Duration(cfg.ShutdownDelaySeconds) * time.Second,
		Drain:       time.Duration(cfg.ShutdownDrainSeconds) * time.Second,
		ForcedGrace: forcedGrace,
	}, logger)
	stopHurry()

	shutdownCtx, cancel := context.WithTimeout(context.Background(), tailBudget)
	defer cancel()
	_ = metricsSrv.Shutdown(shutdownCtx)
	if err := srv.Shutdown(shutdownCtx); err != nil {
		logger.Error("graceful shutdown incomplete", "err", err)
	}
	if background != nil {
		// Best-effort memory extraction shares the remaining tail budget.
		if err := background.Shutdown(shutdownCtx); err != nil {
			logger.Error("background job drain failed", "err", err)
		}
	}
	outboundhttp.CloseIdleConnections()
	logger.Info("edge stopped")
}
