// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"context"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"strings"
	"time"

	"github.com/alicangunduz/raggie/services/edge/internal/config"
	"github.com/alicangunduz/raggie/services/edge/internal/llm"
	"github.com/alicangunduz/raggie/services/edge/internal/locale"
	"github.com/alicangunduz/raggie/services/edge/internal/ports"
	"github.com/alicangunduz/raggie/services/edge/internal/rag"
)

// ─────────────────────────── run-task (server-to-server) ───────────────────────────

// runTaskRequest is the body the scheduler worker POSTs to execute one scheduled
// task headlessly. It mirrors a normal chat turn's knobs (web/deep/model/style)
// but carries no conversation/session: the run is stateless and the worker stores
// the answer in the notifications inbox itself.
type runTaskRequest struct {
	WorkspaceID string `json:"workspace_id"`
	UserID      string `json:"user_id"`
	Prompt      string `json:"prompt"`
	WebSearch   bool   `json:"web_search"`
	DeepSearch  bool   `json:"deep_search"`
	Model       string `json:"model"`
	AnswerStyle string `json:"answer_style"`
}

type runTaskResponse struct {
	Answer string `json:"answer"`
}

// runTaskHandler: POST /api/v1/internal/run-task — server-to-server execution of a
// single scheduled task. Guarded by the INTERNAL_API_SECRET shared secret (header
// X-Internal-Secret, constant-time compared); empty secret disables the endpoint
// (503). It runs the SAME retrieval + assembly + LLM pipeline a chat turn would,
// but headless: no SSE, no conversation persisted, and NO memory extraction (a
// scheduled run must not pollute the user's durable memory). The chat stream is
// drained one-shot (like generateSubQueries) to collect the full answer content;
// reasoning deltas are ignored.
func runTaskHandler(cfg config.Config, deps Deps, logger *slog.Logger) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		// Feature gate: an unset secret means the scheduled-tasks integration is not
		// configured — the endpoint is dormant.
		if cfg.InternalAPISecret == "" {
			writeError(w, r, http.StatusServiceUnavailable, errCodeUnavailable)
			return
		}
		// Constant-time secret check (avoids leaking the secret via timing).
		got := r.Header.Get("X-Internal-Secret")
		if subtle.ConstantTimeCompare([]byte(got), []byte(cfg.InternalAPISecret)) != 1 {
			writeError(w, r, http.StatusUnauthorized, errCodeUnauth)
			return
		}
		// Without WSInfo the owner's access cannot be re-checked: refuse.
		if deps.RAG == nil || deps.Chat == nil || deps.chatAuthUnavailable() {
			writeError(w, r, http.StatusServiceUnavailable, errCodeUnavailable)
			return
		}

		var req runTaskRequest
		if err := decodeJSONBody(w, r, 1<<20, &req); errors.Is(err, errBodyTooLarge) {
			writeError(w, r, http.StatusRequestEntityTooLarge, errCodeTooLarge)
			return
		} else if err != nil || req.WorkspaceID == "" || strings.TrimSpace(req.Prompt) == "" {
			writeError(w, r, http.StatusBadRequest, errCodeBadRequest)
			return
		}
		ctx := r.Context()

		// The task runs with its OWNER's authority, so re-check right now that
		// the owner is still an active user with access to the workspace (they
		// may have been removed or deactivated since the task was scheduled).
		// Same rule as the interactive chat path; fail closed on errors.
		if deps.WSInfo != nil {
			if req.UserID == "" {
				writeError(w, r, http.StatusForbidden, errCodeForbidden)
				return
			}
			allowed, aerr := deps.WSInfo.UserCanAccessWorkspace(ctx, req.UserID, req.WorkspaceID)
			if aerr != nil || !allowed {
				if aerr != nil {
					logger.Error("run-task owner access check", "err", aerr,
						"workspace_id", req.WorkspaceID, "user_id", req.UserID, "request_id", requestIDOf(ctx))
				}
				writeError(w, r, http.StatusForbidden, errCodeForbidden)
				return
			}
		}

		// A scheduled run has no browser: server-authored text follows the task
		// owner's stored language, else the default locale.
		loc := requestLocale(ctx)
		if deps.Store != nil && req.UserID != "" {
			if pref, perr := deps.Store.UserLocale(ctx, req.UserID); perr == nil {
				loc = locale.Resolve(locale.Inputs{UserPreference: pref}, loc)
				ctx = locale.WithContext(ctx, loc)
				// writeError reads the locale from r, so later errors follow it too.
				r = r.WithContext(ctx)
			}
		}

		wsSet := []string{req.WorkspaceID}
		model := strings.TrimSpace(req.Model)
		if model == "" {
			model = cfg.ChatModel
		}
		if !cfg.HasModel(model) {
			writeError(w, r, http.StatusBadRequest, errCodeBadRequest)
			return
		}

		// Per-workspace chat-intelligence flags (gating for web/deep + personalization),
		// exactly like chat.go. Zero value (no DB) leaves every feature off → documents.
		feats := deps.workspaceFeatures(ctx, req.WorkspaceID)

		// Persona (opt-in, INTERNAL only): same gates as chat.go. The scheduler only
		// ever runs tasks for authenticated INTERNAL users, but we still require a
		// non-empty user_id so an empty owner can never be personalized. Fail-soft.
		persona := ""
		if cfg.PersonalizationEnabled && req.UserID != "" && feats.Personalization && deps.Store != nil {
			if p, perr := deps.Store.GetUserPersona(ctx, req.UserID); perr == nil {
				persona = p.Block(loc)
			}
		}
		// Durable memory (opt-in): prepend remembered facts, same gate as chat.go.
		// We READ memory but never WRITE it here (no extraction for scheduled runs).
		if memoryAllowed(cfg, feats, req.UserID, deps) {
			if facts, merr := deps.memoryStore().GetUserMemory(ctx, req.UserID, 20); merr == nil && len(facts) > 0 {
				mem := memoryBlock(loc, facts)
				if persona == "" {
					persona = mem
				} else {
					persona += "\n\n" + mem
				}
			}
		}

		// Pick the context source the SAME way chat.go does:
		//   deep_search + web gated → deep pipeline; else web_search + gated → single
		//   Brave search; else documents retrieval. Web/deep fail-open: if they yield
		//   nothing we fall back to the documents answer (never hard-fail a run).
		webGated := cfg.WebSearchEnabled && deps.Web != nil && feats.WebSearch
		useDeep := req.DeepSearch && webGated
		var webResults []ports.WebResult
		useWeb := false
		if useDeep {
			_, webResults = deepWebResearch(ctx, deps, logger, cfg, model, req.Prompt, nil)
			if len(webResults) == 0 {
				useDeep = false // fall back to documents below
			}
		} else if webGated && req.WebSearch {
			query := generateWebQuery(ctx, deps, logger, model, req.Prompt)
			if rs := singleWebResearch(ctx, deps, logger, cfg, req.Prompt, query); len(rs) > 0 {
				webResults = rs
				useWeb = true
			}
		}

		// Documents retrieval (the default, and the fallback when web/deep is empty).
		var res rag.RetrieveResult
		if !useDeep && !useWeb {
			r2, err := deps.RAG.Retrieve(ctx, wsSet, req.Prompt, cfg.RetrieveCandidateK, cfg.RetrieveContextK)
			if errors.Is(err, llm.ErrUpstreamBusy) {
				shed(w, r)
				return
			}
			if err != nil {
				logger.Error("run-task retrieval failed",
					"err", err, "workspace_id", req.WorkspaceID, "user_id", req.UserID,
					"request_id", requestIDOf(ctx), queryLogAttr(req.Prompt))
				writeError(w, r, http.StatusBadGateway, errCodeRetrieval)
				return
			}
			res = r2
		}

		// Assemble messages (docs/web/deep variant). No system prompt override, no
		// history (a scheduled run is a fresh single turn); honor the answer style.
		var msgs []ports.Message
		switch {
		case useDeep:
			msgs = deps.RAG.AssembleDeepMessages("", nil, webEvidenceContextBlock(webResults), req.Prompt, cfg.HistoryMaxMessages, persona, req.AnswerStyle, loc)
		case useWeb:
			msgs = deps.RAG.AssembleWebMessages("", nil, webEvidenceContextBlock(webResults), req.Prompt, cfg.HistoryMaxMessages, persona, req.AnswerStyle, loc)
		default:
			msgs = deps.RAG.AssembleMessages("", nil, res.ContextText, req.Prompt, cfg.HistoryMaxMessages, res.LowConfidence, persona, req.AnswerStyle, loc)
		}

		// One-shot LLM: start the stream (may shed) and DRAIN it for the full answer
		// content. Reuse the configured default reasoning effort. Model empty →
		// provider falls back to the configured default chat model.
		effort := cfg.ReasoningEffort
		if !cfg.SupportsReasoning(model) {
			effort = ""
		}
		stream, serr := deps.Chat.Stream(ctx, ports.ChatRequest{
			Messages: msgs, Model: model, ReasoningEffort: effort,
		})
		if errors.Is(serr, llm.ErrUpstreamBusy) {
			shed(w, r)
			return
		}
		if serr != nil {
			logger.Error("run-task chat upstream failed",
				"err", serr, "workspace_id", req.WorkspaceID, "user_id", req.UserID,
				"request_id", requestIDOf(ctx), "model", req.Model, queryLogAttr(req.Prompt))
			writeError(w, r, http.StatusBadGateway, errCodeUpstream)
			return
		}
		var b strings.Builder
		completed := false
		for chunk := range stream { // drain fully so the pool slot is released
			if chunk.Done {
				completed = true
				break
			}
			// Collect only answer content; reasoning (CoT) is ignored for the stored result.
			b.WriteString(chunk.Delta)
		}
		answer := strings.TrimSpace(b.String())
		if !completed || answer == "" {
			logger.Error("run-task produced no answer",
				"workspace_id", req.WorkspaceID, "user_id", req.UserID,
				"request_id", requestIDOf(ctx), "completed", completed)
			writeError(w, r, http.StatusBadGateway, errCodeUpstream)
			return
		}
		writeJSON(w, http.StatusOK, runTaskResponse{Answer: answer})
	}
}

// ─────────────────────────── schedule parse (user-facing) ───────────────────────────

// maxScheduleTextLen bounds the natural-language schedule request (runes) so a
// pathological body cannot blow up the meta-prompt / token cost.
const maxScheduleTextLen = 2000

type scheduleParseRequest struct {
	Text     string `json:"text"`
	Timezone string `json:"timezone"`
}

type scheduleParseResponse struct {
	Cron    string `json:"cron"`
	Prompt  string `json:"prompt"`
	Name    string `json:"name"`
	Summary string `json:"summary"`
}

// scheduleParseHandler: POST /api/v1/schedule/parse — authenticated INTERNAL users
// (aud=admin access token, same as the skills/generate endpoint). One non-streamed
// completion turns a natural-language schedule request into {cron, prompt, name,
// summary}. Drained one-shot on the chat pool. Tolerant parsing (strips code
// fences / extracts the first {...} block); the cron is validated to exactly 5
// space-separated fields.
func scheduleParseHandler(cfg config.Config, deps Deps, logger *slog.Logger) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if _, ok := adminUserID(cfg, deps, w, r); !ok {
			return
		}
		if deps.Chat == nil {
			writeError(w, r, http.StatusServiceUnavailable, errCodeUnavailable)
			return
		}

		var req scheduleParseRequest
		if err := decodeJSONBody(w, r, 1<<16, &req); errors.Is(err, errBodyTooLarge) {
			writeError(w, r, http.StatusRequestEntityTooLarge, errCodeTooLarge)
			return
		} else if err != nil {
			writeError(w, r, http.StatusBadRequest, errCodeBadRequest)
			return
		}
		text := strings.TrimSpace(req.Text)
		if text == "" {
			writeError(w, r, http.StatusBadRequest, errCodeBadRequest)
			return
		}
		if len([]rune(text)) > maxScheduleTextLen {
			text = string([]rune(text)[:maxScheduleTextLen])
		}

		// Resolve the timezone (default cfg.DefaultTimezone, i.e. DEFAULT_TIMEZONE or
		// UTC); an unknown zone falls back to it so a bad client value can't fail the parse.
		tz := strings.TrimSpace(req.Timezone)
		if tz == "" {
			tz = cfg.DefaultTimezone
		}
		loc, lerr := time.LoadLocation(tz)
		if lerr != nil {
			tz = cfg.DefaultTimezone
			loc, _ = time.LoadLocation(tz)
			if loc == nil {
				loc = time.UTC
			}
		}
		// {NOW}: prefer a weekday-bearing human form so the model can resolve
		// "tomorrow"/"next Monday" correctly; the zone name is supplied separately.
		now := time.Now().In(loc).Format("2006-01-02 15:04, Monday")
		sys := strings.NewReplacer("{NOW}", now, "{TZ}", tz).Replace(locale.Pick(scheduleParsePrompt, requestLocale(r.Context())))

		genCtx, cancel := context.WithTimeout(r.Context(), 30*time.Second)
		defer cancel()
		msgs := []ports.Message{
			{Role: ports.RoleSystem, Content: sys},
			{Role: ports.RoleUser, Content: text},
		}
		// Low temperature for deterministic structure; small cap (the JSON is tiny).
		// Model empty → provider falls back to the configured default chat model.
		stream, err := deps.Chat.Stream(genCtx, ports.ChatRequest{Messages: msgs, Temperature: 0.2, MaxTokens: 400})
		if err != nil {
			if errors.Is(err, llm.ErrUpstreamBusy) {
				writeError(w, r, http.StatusServiceUnavailable, errCodeBusy)
				return
			}
			logger.Error("schedule parse upstream failed", "err", err, "request_id", requestIDOf(r.Context()))
			writeError(w, r, http.StatusUnprocessableEntity, errCodeParseFailed)
			return
		}
		var b strings.Builder
		completed := false
		var streamErr error
		for chunk := range stream { // drain fully so the pool slot is released
			if chunk.Err != nil {
				streamErr = chunk.Err
				break
			}
			if chunk.Done {
				completed = true
				break
			}
			b.WriteString(chunk.Delta) // ignore reasoning deltas
		}

		if streamErr != nil || !completed {
			logger.Warn("schedule parse stream incomplete", "err", streamErr, "request_id", requestIDOf(r.Context()))
			writeError(w, r, http.StatusUnprocessableEntity, errCodeParseFailed)
			return
		}
		parsed, perr := parseScheduleJSON(b.String())
		if perr != nil {
			logger.Warn("schedule parse failed", "err", perr, "request_id", requestIDOf(r.Context()))
			writeError(w, r, http.StatusUnprocessableEntity, errCodeParseFailed)
			return
		}
		writeJSON(w, http.StatusOK, parsed)
	}
}

// errBadCron is returned when the model's cron is not exactly 5 space-separated
// fields (a standard 5-field crontab). Surfaced to the client as a friendly 422.
var errBadCron = errors.New("cron must have exactly 5 fields")

// parseScheduleJSON extracts the model's JSON answer tolerantly: it strips any
// ```fences```, isolates the first {...} block, unmarshals it, and validates the
// cron has exactly 5 fields. Whitespace is normalised in the cron so "09  *  *"
// can't pass with empty fields.
func parseScheduleJSON(raw string) (scheduleParseResponse, error) {
	var out scheduleParseResponse
	s := extractJSONObject(raw)
	if s == "" {
		return out, errors.New("no JSON object in model output")
	}
	if err := json.Unmarshal([]byte(s), &out); err != nil {
		return out, err
	}
	out.Cron = strings.Join(strings.Fields(out.Cron), " ")
	out.Prompt = strings.TrimSpace(out.Prompt)
	out.Name = strings.TrimSpace(out.Name)
	out.Summary = strings.TrimSpace(out.Summary)
	if len(strings.Fields(out.Cron)) != 5 {
		return out, errBadCron
	}
	return out, nil
}

// extractJSONObject returns the first balanced {...} block in s (after stripping a
// leading ```json / trailing ``` fence). Brace counting ignores braces inside
// double-quoted strings (respecting backslash escapes) so a "{" in a value can't
// unbalance the scan. Returns "" when no object is found.
func extractJSONObject(s string) string {
	s = strings.TrimSpace(s)
	// Strip a leading code fence (```json / ```), if present, and any trailing one.
	if strings.HasPrefix(s, "```") {
		if nl := strings.IndexByte(s, '\n'); nl >= 0 {
			s = s[nl+1:]
		}
		s = strings.TrimSuffix(strings.TrimSpace(s), "```")
	}
	start := strings.IndexByte(s, '{')
	if start < 0 {
		return ""
	}
	depth := 0
	inStr := false
	esc := false
	for i := start; i < len(s); i++ {
		c := s[i]
		if inStr {
			switch {
			case esc:
				esc = false
			case c == '\\':
				esc = true
			case c == '"':
				inStr = false
			}
			continue
		}
		switch c {
		case '"':
			inStr = true
		case '{':
			depth++
		case '}':
			depth--
			if depth == 0 {
				return s[start : i+1]
			}
		}
	}
	return ""
}
