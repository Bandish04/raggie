// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"strings"

	"github.com/alicangunduz/raggie/services/edge/internal/agent"
	"github.com/alicangunduz/raggie/services/edge/internal/config"
	"github.com/alicangunduz/raggie/services/edge/internal/llm"
	"github.com/alicangunduz/raggie/services/edge/internal/locale"
	"github.com/alicangunduz/raggie/services/edge/internal/ports"
	"github.com/alicangunduz/raggie/services/edge/internal/rag"
	"github.com/alicangunduz/raggie/services/edge/internal/store"
)

// unifiedTurnState carries the already-computed shared setup from chatHandler
// into the unified agentic path so it does not re-do retrieval/persona/etc.
type unifiedTurnState struct {
	userID   string
	widget   bool // anonymous EXTERNAL widget session
	convID   string
	turn     botTurn
	history  []ports.Message
	res      rag.RetrieveResult
	feats    store.WorkspaceFeatureFlags
	persona  string
	effort   string
	jiraGate JiraGatePort
	attach   func([]ports.Message)
	locale   locale.Locale
}

// runUnifiedTurn executes one chat turn through the unified agentic loop.
// RAG documents are always-on grounding; user-toggled web/deep are PRE-FETCHED
// directly (like the legacy path) and folded into the seeded prompt as additional
// context sources, so the SINGLE agent Stream answers with web grounding already
// in place — no extra round-trip, model-agnostic. MCP tools are the ONLY model-
// decided tools, and only when the resolved chat model supports tool-calling
// (cfg.SupportsTools); on a non-tool model MCP is a no-op, not an error. With no
// MCP tools the registry is empty ⇒ exactly ONE Stream call (the agent.go
// invariant), identical to the legacy documents path.
//
// SSE events preserved: meta, sources, web_offer, web_unavailable, deep_progress,
// thinking, tool_call, tool_result, bare data {delta}, error, done, [DONE].
func runUnifiedTurn(
	w http.ResponseWriter, r *http.Request, cfg config.Config, deps Deps, logger *slog.Logger,
	req chatStreamRequest, st unifiedTurnState,
) {
	ctx := r.Context()
	res := st.res
	feats := st.feats

	// Web/deep are gated exactly like the legacy path (global flag + searcher +
	// per-workspace flag). MCP is gated by the global flag, a connected jira
	// integration, the per-turn opt-in, AND the model supporting tool-calling.
	webGated := webSearchGated(cfg, deps, feats, st.widget)

	// deep_research takes precedence over single web (as in the legacy path): when
	// both are requested only deep is run so we never fire two web pipelines.
	useDeep := req.DeepSearch && webGated && allowed(req.AllowTools, "deep_research")
	useWeb := req.WebSearch && webGated && !useDeep && allowed(req.AllowTools, "web_search")

	// Resolve the chat model the same way llm.Stream does (per-request override,
	// else the config default) so the tool-capability gate matches what actually
	// runs upstream.
	model := req.Model
	if model == "" {
		model = cfg.ChatModel
	}
	// toolsModelOK gates whether we may advertise ANY tools (MCP) to this model. A
	// model not in TOOL_MODELS never receives a tools/tool_choice payload, so it
	// can't 4xx mid-stream — MCP simply becomes a no-op for that turn.
	toolsModelOK := cfg.SupportsTools(model)

	// ── Open the SSE response ─────────────────────────────────────────────────
	h := w.Header()
	h.Set("Content-Type", "text/event-stream")
	h.Set("Cache-Control", "no-cache")
	h.Set("Connection", "keep-alive")
	h.Set("X-Accel-Buffering", "no")
	flusher, _ := w.(http.Flusher)
	flush := func() {
		if flusher != nil {
			flusher.Flush()
		}
	}

	// emit writes an SSE event (empty name ⇒ bare data line) and flushes.
	emit := func(event string, data []byte) {
		if event == "" {
			fmt.Fprintf(w, "data: %s\n\n", data)
		} else {
			fmt.Fprintf(w, "event: %s\ndata: %s\n\n", event, data)
		}
		flush()
	}

	turn := st.turn
	if turn.conversationID == "" {
		turn.conversationID = st.convID
	}
	writeMetaEvent(w, turn)
	flush()

	// Offer a web search when the documents didn't cover the question and the user
	// hasn't enabled any web mode (mirrors the legacy web_offer behaviour).
	if webGated && !useWeb && !useDeep {
		offerReason := ""
		if strings.TrimSpace(res.ContextText) == "" {
			offerReason = "empty"
		} else if res.LowConfidence {
			offerReason = "low_confidence"
		}
		if offerReason != "" {
			offer, _ := json.Marshal(map[string]string{"question": req.Message, "reason": offerReason})
			fmt.Fprintf(w, "event: web_offer\ndata: %s\n\n", offer)
			flush()
		}
	}
	// The user toggled web/deep on but it is disabled for this workspace — tell
	// the client (it renders a localized note), matching the legacy path.
	if cfg.WebSearchEnabled && deps.Web != nil && !feats.WebSearch && (req.WebSearch || req.DeepSearch) {
		fmt.Fprintf(w, "event: web_unavailable\ndata: {}\n\n")
		flush()
	}

	// ── Web/deep grounding path ────────────────────────────────────────────────
	// On tool-capable models, web/deep are real agent tools and the model decides
	// whether to call them (tool_choice=auto). On non-tool models, retain the
	// legacy pre-fetch fallback so toggled web/deep still works without sending a
	// tools payload upstream.
	sources := []rag.ContextSource{
		{Kind: rag.SourceDocuments, Text: res.ContextText, LowConfidence: res.LowConfidence},
	}
	var webResults []ports.WebResult

	if useDeep && !toolsModelOK {
		// Status event BEFORE the (blocking, up-to-20s) sub-query generation so the
		// UI shows activity during the wait instead of a silent pause.
		emit("deep_progress", mustJSON(map[string]string{"status": "generating_queries"}))

		_, rs := deepWebResearch(ctx, deps, logger, cfg, req.Model, req.Message, emit)

		if len(rs) == 0 {
			emit("web_unavailable", []byte("{}"))
		} else {
			webResults = rs
			sources = append(sources, rag.ContextSource{
				Kind: rag.SourceDeep,
				Text: webEvidenceContextBlockFrom(rs, len(res.Chunks)+1),
			})
		}
	} else if useWeb && !toolsModelOK {
		// Reformulate the (possibly conversational) message into ONE focused search
		// query before hitting Brave; fail-soft to the raw message on any error.
		query := generateWebQuery(ctx, deps, logger, req.Model, req.Message)
		progress(emit, "searching")
		progress(emit, "reading")
		rs := singleWebResearch(ctx, deps, logger, cfg, req.Message, query)
		progress(emit, "reranking")
		if len(rs) == 0 {
			emit("web_unavailable", []byte("{}"))
		} else {
			webResults = rs
			sources = append(sources, rag.ContextSource{
				Kind: rag.SourceWeb,
				Text: webEvidenceContextBlockFrom(rs, len(res.Chunks)+1),
			})
		}
	}

	// One ordered registry drives live cards, persisted history, and citation
	// numbering: document chunks first, then web/deep evidence.
	sourceCards := combinedSourceCards(res.Chunks, webResults)
	sourceState := newToolSourceState(sourceCards)
	sourceState.emit(emit)

	// ── Build the model-decided tool registry (gated by model capability) ─────
	// Tool-capable models may see web/deep and MCP tools. Empty registry ⇒ exactly
	// one Stream call (the agent.go invariant), identical to the legacy documents
	// path.
	reg := agent.NewRegistry()
	if toolsModelOK {
		addWebResearchTools(reg, deps, logger, cfg, req, sourceState, emit, useWeb, useDeep)
	}
	if mcpPermitted(st.userID) && req.MCPTools && allowed(req.AllowTools, "mcp") && deps.MCP != nil && st.jiraGate != nil {
		if !toolsModelOK {
			// Non-tool model: MCP is a no-op (NOT an error) — never send tools so the
			// upstream can't reject the request mid-stream.
			logger.Warn("model does not support tool-calling; skipping MCP tools", "model", model, "workspace_id", req.WorkspaceID)
		} else if has, herr := st.jiraGate.HasConnectedJira(ctx, req.WorkspaceID); herr != nil {
			logger.Warn("jira integration check failed; proceeding without MCP tools", "err", herr, "workspace_id", req.WorkspaceID)
		} else if has {
			if defs, lerr := deps.MCP.ListTools(ctx); lerr != nil {
				logger.Warn("mcp tools/list failed; proceeding without MCP tools", "err", lerr)
			} else {
				addMCPTools(reg, deps.MCP, defs, req.AllowTools, cfg.MCPAllowWriteTools, req.Message)
			}
		}
	}

	// Assemble the grounded prompt from documents + any pre-fetched web/deep block.
	msgs := deps.RAG.AssembleUnifiedMessages(req.SystemPrompt, st.history, sources, req.Message, cfg.HistoryMaxMessages, st.persona, req.AnswerStyle, st.locale)
	if st.attach != nil {
		st.attach(msgs)
	}

	// ── Run the agentic loop ──────────────────────────────────────────────────
	// toolChoice intentionally stays "auto": when tools are toggled on, the model
	// may call them but is not forced to. With an empty registry no tools/tool_choice
	// are sent at all (exactly one Stream call, identical to the legacy documents
	// path).
	toolChoice := "auto"
	progress(emit, "synthesizing")
	result := agent.RunWithTools(ctx, reg, agent.RunParams{
		Chat:                  deps.Chat,
		Messages:              msgs,
		Temperature:           req.Temperature,
		Model:                 req.Model,
		ReasoningEffort:       st.effort,
		ToolChoice:            toolChoice,
		MaxIterations:         cfg.AgentMaxIterations,
		IterLimitNote:         locale.Pick(iterLimitNote, st.locale),
		IterLimitThinkingNote: locale.Pick(iterLimitThinkingNote, st.locale),
		StreamReasoning:       cfg.StreamReasoning,
	}, emit)

	streamErrWritten := false
	if result.Err != nil {
		// Headers already sent — surface a graceful SSE error (status can't change).
		logger.Error("unified chat upstream failed",
			"err", result.Err, "workspace_id", req.WorkspaceID, "user_id", st.userID,
			"request_id", requestIDOf(ctx), "model", req.Model, queryLogAttr(req.Message))
		if errors.Is(result.Err, llm.ErrUpstreamBusy) {
			writeStreamError(w, r, errCodeBusy)
		} else {
			writeStreamError(w, r, errCodeStream)
		}
		flush()
		streamErrWritten = true
	}

	answer := result.Answer
	usage := result.Usage
	completed := result.Completed
	sourcesJSON := sourceState.JSON()

	// Mid-stream failure with the client still connected: surface a friendly note.
	if !completed && ctx.Err() == nil && !streamErrWritten && result.Err == nil {
		logger.Error("unified chat stream ended without completion",
			"workspace_id", req.WorkspaceID, "user_id", st.userID,
			"request_id", requestIDOf(ctx), "model", req.Model, queryLogAttr(req.Message))
		writeStreamError(w, r, errCodeStream)
		flush()
	}

	// ── Persist the BOT turn (partial if aborted) + terminal markers ──────────
	usedTokens := 0
	if usage != nil {
		usedTokens = usage.CompletionTokens
	}
	botMsgID := persistBotTurn(ctx, deps, logger, turn, req.WorkspaceID, answer, usedTokens,
		string(sourcesJSON), completed, withToolAudit(requestMessageAudit(req), result.ToolExecutions))

	if completed && botMsgID != "" {
		fmt.Fprintf(w, "event: done\ndata: {\"message_id\":%q}\n\n", botMsgID)
		flush()
	}
	if drainCancelled(ctx) {
		writeReconnectEvent(w, r, turn)
		flush()
	}
	fmt.Fprint(w, "data: [DONE]\n\n")
	flush()

	// Durable memory extraction (opt-in, authenticated INTERNAL chats only).
	if completed && memoryAllowed(cfg, st.feats, st.userID, deps) && deps.Chat != nil {
		scheduleMemoryExtraction(deps, logger, st.locale, st.userID, req.Model, req.Message, answer)
	}
}

// mcpPermitted reports whether the caller may use MCP tools at all: only an
// authenticated INTERNAL user (userID comes solely from a verified aud=admin
// token). Anonymous widget sessions and unauthenticated mode never qualify.
func mcpPermitted(userID string) bool {
	return userID != ""
}

// allowed reports whether a tool name passes the skill allow-list. A nil list
// (no skill restriction) allows everything (inherit-all). An empty non-nil list
// allows nothing. Otherwise only listed names pass. req.AllowTools comes only
// from the resolved skill policy, never from the client.
func allowed(allowList []string, name string) bool {
	if allowList == nil {
		return true
	}
	for _, a := range allowList {
		if a == name {
			return true
		}
	}
	return false
}
