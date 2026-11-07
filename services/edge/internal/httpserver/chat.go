// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"slices"
	"strings"
	"time"

	"github.com/alicangunduz/raggie/services/edge/internal/agent"
	"github.com/alicangunduz/raggie/services/edge/internal/config"
	"github.com/alicangunduz/raggie/services/edge/internal/llm"
	"github.com/alicangunduz/raggie/services/edge/internal/locale"
	"github.com/alicangunduz/raggie/services/edge/internal/ports"
	"github.com/alicangunduz/raggie/services/edge/internal/store"
	"github.com/alicangunduz/raggie/services/edge/internal/widgetauth"
)

type chatStreamRequest struct {
	WorkspaceID      string          `json:"workspace_id"`
	WorkspaceIDs     []string        `json:"workspace_ids"` // "all workspaces" search; empty = just WorkspaceID
	ConversationID   string          `json:"conversation_id"`
	SessionToken     string          `json:"session_token"`
	Message          string          `json:"message"`
	SystemPrompt     string          `json:"system_prompt"`
	History          []ports.Message `json:"history"`
	Temperature      float32         `json:"temperature"`
	WebSearch        bool            `json:"web_search"`       // user opted into a web-augmented answer
	DeepSearch       bool            `json:"deep_search"`      // user opted into deep research (multi-sub-query web synthesis)
	MCPTools         bool            `json:"mcp_tools"`        // user opted into MCP tools (e.g. connected Jira) for this turn
	AllowTools       []string        `json:"allow_tools"`      // ignored from clients; set from the resolved skill policy (nil = no filter)
	Attachments      []attachment    `json:"attachments"`      // optional images (vision)
	Model            string          `json:"model"`            // optional per-request chat model override (else config default)
	AnswerStyle      string          `json:"answer_style"`     // optional response style: corporate|short|instructive|balanced
	ReasoningEffort  string          `json:"reasoning_effort"` // optional CoT depth: low|medium|high (else config default)
	SkillID          string          `json:"skill_id"`
	SkillVersion     int             `json:"skill_version"`
	ResumeMessageID  string          `json:"resume_message_id"` // regenerate a drain-interrupted assistant turn instead of asking anew
	Locale           string          `json:"locale"`            // optional UI locale (en|tr) for server-authored text; answers follow the question's language
	resolvedSkill    *store.ResolvedSkill
	resolvedProvider string
}

// attachment is a client-supplied image for a vision-capable model. data_url is
// a base64 data: URL; mime is informational.
type attachment struct {
	Type    string `json:"type"`
	DataURL string `json:"data_url"`
	MIME    string `json:"mime"`
}

const (
	maxAttachments = 4
	maxAttachBytes = 5 * 1024 * 1024 // ~5MB per image (base64-inflated length)
)

// chatHandler serves POST /api/v1/chat/stream: dedup, retrieve (A2), persist the
// USER turn, stream the answer over SSE, then persist the BOT turn (partial if
// aborted) and emit chat.completed only on full completion (ARCHITECTURE §7).
func chatHandler(cfg config.Config, deps Deps, logger *slog.Logger) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if deps.RAG == nil || deps.Chat == nil {
			writeError(w, r, http.StatusServiceUnavailable, errCodeUnavailable)
			return
		}
		// Graceful shutdown: refuse new streams once draining, and register this
		// one so it can finish (or be told to reconnect) within the drain window.
		if deps.Drain != nil {
			streamCtx, release, ok := deps.Drain.Track(r.Context())
			if !ok {
				allowOriginForError(w, r)
				setRetryAfter(w, drainRetryAfterSeconds*time.Second)
				writeError(w, r, http.StatusServiceUnavailable, errCodeDraining)
				return
			}
			defer release()
			r = r.WithContext(streamCtx)
		}
		// Per-replica stream cap (EDGE_MAX_SSE_CONNECTIONS): shed before any SSE
		// byte so the client retries, possibly on another replica.
		releaseSlot, admitted := deps.Streams.Acquire()
		if !admitted {
			allowOriginForError(w, r)
			shed(w, r)
			return
		}
		defer releaseSlot()
		// No WSInfo (no database) means no way to verify the token, the workspace
		// type or membership: refuse instead of serving chat unauthenticated.
		if deps.chatAuthUnavailable() {
			writeError(w, r, http.StatusServiceUnavailable, errCodeUnavailable)
			return
		}
		maxBody := cfg.ChatMaxBodyBytes
		if maxBody <= 0 {
			maxBody = config.DefaultChatMaxBodyBytes
		}
		var req chatStreamRequest
		decodeErr := decodeJSONBody(w, r, maxBody, &req)
		// Locale for server-authored text: explicit request field > stored user
		// preference (applied after authentication) > Accept-Language > default.
		loc := locale.Resolve(locale.Inputs{
			Explicit:       req.Locale,
			AcceptLanguage: r.Header.Get("Accept-Language"),
		}, cfg.DefaultLocale)
		r = r.WithContext(locale.WithContext(r.Context(), loc))
		if err := decodeErr; errors.Is(err, errBodyTooLarge) {
			writeError(w, r, http.StatusRequestEntityTooLarge, errCodeTooLarge)
			return
		} else if err != nil || req.WorkspaceID == "" || (req.Message == "" && req.ResumeMessageID == "") ||
			len(req.WorkspaceIDs) > maxWorkspaceIDs || (req.ResumeMessageID != "" && !uuidLike(req.ResumeMessageID)) ||
			!validAttachments(req.Attachments) {
			writeError(w, r, http.StatusBadRequest, errCodeBadRequest)
			return
		}
		ctx := r.Context()

		// Workspace set: a single workspace, or several for an "all workspaces" search.
		wsSet := req.WorkspaceIDs
		if len(wsSet) == 0 {
			wsSet = []string{req.WorkspaceID}
		}
		var userID string // set for authenticated INTERNAL chats; ties history to the user
		// sessionKey binds anonymous conversations. For the widget it is the
		// server-minted token sid — the client-sent session_token is attacker-
		// controlled and ignored there. Only the unauthenticated hot-path mode
		// (no WSInfo) keeps the legacy client value.
		sessionKey := req.SessionToken
		widgetSession := false // an anonymous EXTERNAL widget principal

		// Authorize the chat request against the workspace (ARCHITECTURE §9/§10).
		// EXTERNAL = public widget surface (aud=widget token bound to the workspace
		// + allow-listed Origin). INTERNAL = an aud=admin access token whose user
		// has effective access to EVERY requested workspace (SUPER_ADMIN only
		// within its own org; platform admins across orgs). Without WSInfo the
		// handler already refused above, except in the package's own tests.
		if deps.WSInfo != nil {
			typ, corsOrigins, _, _, err := deps.WSInfo.WorkspaceWidget(ctx, req.WorkspaceID)
			if err != nil {
				writeError(w, r, http.StatusNotFound, errCodeNotFound)
				return
			}
			if typ == "EXTERNAL" {
				wsSet = []string{req.WorkspaceID} // widget is single-workspace
				origin := r.Header.Get("Origin")
				if origin == "" || !slices.Contains(corsOrigins, origin) {
					writeError(w, r, http.StatusForbidden, errCodeForbidden)
					return
				}
				// The origin is allow-listed: from here on every response
				// (including 401/429) is readable by the widget script.
				allowOrigin(w, origin)
				claims, verr := widgetauth.Verify(cfg.WidgetTokenSecret, bearer(r), time.Now(),
					time.Duration(cfg.WidgetTokenTTLSeconds)*time.Second)
				if verr != nil || claims.WorkspaceID != req.WorkspaceID {
					writeError(w, r, http.StatusUnauthorized, errCodeUnauth)
					return
				}
				sessionKey = claims.SessionID
				widgetSession = true
				// Anonymous surface: limit per widget session AND per client IP
				// (rotating tokens from one IP still hits the IP bucket).
				if d, ok := checkRateLimits(ctx, deps.RateLimiter, logger,
					rateLimitCheck{"chat:wsess:" + claims.SessionID, sessionKeyLimit(cfg, claims.SessionID)},
					rateLimitCheck{"chat:wip:" + req.WorkspaceID + ":" + clientIP(r, cfg.TrustedProxyCIDRs), cfg.RateLimitChatWidgetIPPerMinute},
				); !ok {
					setRetryAfter(w, d.RetryAfter)
					writeError(w, r, http.StatusTooManyRequests, errCodeRateLimited)
					return
				}
			} else {
				sessionKey = "" // INTERNAL conversations are bound to the user
				claims, verified := verifiedAdminClaims(cfg, deps, r)
				if !verified {
					writeError(w, r, http.StatusUnauthorized, errCodeUnauth)
					return
				}
				userID, _ = claims["sub"].(string)
				// Every workspace touched by this turn is authorized: the primary
				// one (conversation owner + policy source) AND each searched one.
				// There is no token-claim bypass: the store applies the org-scoped
				// SUPER_ADMIN rule and the cross-org platform-admin rule. A denied
				// workspace answers like an unknown one (404), so ids from another
				// org cannot be probed for existence.
				for _, ws := range requestedWorkspaces(req.WorkspaceID, wsSet) {
					allowed, aerr := deps.WSInfo.UserCanAccessWorkspace(ctx, userID, ws)
					if aerr != nil {
						logger.Warn("workspace access check failed", "err", aerr, "workspace_id", ws)
					}
					if aerr != nil || !allowed {
						writeError(w, r, http.StatusNotFound, errCodeNotFound)
						return
					}
				}
				if d, ok := checkRateLimits(ctx, deps.RateLimiter, logger,
					rateLimitCheck{"chat:user:" + userID, cfg.RateLimitChatUserPerMinute},
				); !ok {
					setRetryAfter(w, d.RetryAfter)
					writeError(w, r, http.StatusTooManyRequests, errCodeRateLimited)
					return
				}
			}
		}

		// An authenticated user's stored language preference refines the locale
		// when the request did not name one explicitly.
		if userID != "" && deps.Store != nil {
			if _, explicit := locale.Parse(req.Locale); !explicit {
				if pref, perr := deps.Store.UserLocale(ctx, userID); perr == nil {
					loc = locale.Resolve(locale.Inputs{
						UserPreference: pref,
						AcceptLanguage: r.Header.Get("Accept-Language"),
					}, cfg.DefaultLocale)
					ctx = locale.WithContext(ctx, loc)
					r = r.WithContext(ctx)
				}
			}
		}

		if err := resolveChatPolicy(ctx, cfg, deps, userID, &req); err != nil {
			if errors.Is(err, errInvalidChatPolicy) {
				writeError(w, r, http.StatusBadRequest, errCodeBadRequest)
			} else if errors.Is(err, errChatPolicyDenied) {
				writeError(w, r, http.StatusForbidden, errCodeForbidden)
			} else {
				logger.Error("resolve chat policy",
					"err", err, "workspace_id", req.WorkspaceID, "user_id", userID,
					"request_id", requestIDOf(ctx))
				writeError(w, r, http.StatusServiceUnavailable, errCodeUnavailable)
			}
			return
		}

		// Idempotency: a retried Idempotency-Key is rejected (no double LLM call).
		if deps.Bus != nil {
			if key := r.Header.Get("Idempotency-Key"); key != "" {
				if first, err := deps.Bus.AcquireOnce(ctx, key, 10*time.Minute); err == nil && !first {
					writeError(w, r, http.StatusConflict, errCodeConflict)
					return
				}
			}
		}

		// Resume (after a drain-forced `reconnect`): regenerate the interrupted
		// assistant turn in place. The stored user question is reused and no new
		// USER/BOT rows are written. Foreign ids are 404 like any unknown id; an
		// owned id that is not the interrupted last turn is 400. Claiming clears
		// the drain marker; it is restored if we fail before streaming starts.
		resuming := false
		var resume store.ResumeTarget
		// preStreamCleanup undoes reservations if the turn fails before the SSE
		// stream opens (re-arm a claimed resume, drop an unused placeholder).
		preStreamCleanup := func() {}
		defer func() { preStreamCleanup() }()
		if req.ResumeMessageID != "" {
			if deps.Store == nil {
				writeError(w, r, http.StatusBadRequest, errCodeBadRequest)
				return
			}
			t, cerr := deps.Store.ClaimInterruptedMessage(ctx, req.ResumeMessageID, req.WorkspaceID, userID, sessionKey)
			switch {
			case errors.Is(cerr, store.ErrResumeNotFound):
				writeError(w, r, http.StatusNotFound, errCodeNotFound)
				return
			case errors.Is(cerr, store.ErrResumeNotResumable):
				writeError(w, r, http.StatusBadRequest, errCodeBadRequest)
				return
			case cerr != nil:
				logger.Error("claim interrupted message", "err", cerr, "request_id", requestIDOf(ctx))
				writeError(w, r, http.StatusServiceUnavailable, errCodeUnavailable)
				return
			}
			if req.ConversationID != "" && req.ConversationID != t.ConversationID {
				_ = deps.Store.ReleaseInterruptedMessage(context.Background(), req.ResumeMessageID)
				writeError(w, r, http.StatusNotFound, errCodeNotFound)
				return
			}
			resuming, resume = true, t
			req.Message = t.Question
			preStreamCleanup = func() {
				if err := deps.Store.ReleaseInterruptedMessage(context.Background(), req.ResumeMessageID); err != nil {
					logger.Error("release interrupted message", "err", err)
				}
			}
		}

		// (1) Retrieval — A2. Shed on saturation before any SSE bytes. CandidateK
		// chunks are pulled and (when reranking is enabled) reordered, then trimmed
		// to ContextK before the prompt is built — high recall, focused context.
		res, err := deps.RAG.Retrieve(ctx, wsSet, req.Message, cfg.RetrieveCandidateK, cfg.RetrieveContextK)
		if errors.Is(err, llm.ErrUpstreamBusy) {
			shed(w, r)
			return
		}
		if err != nil && drainCancelled(ctx) {
			setRetryAfter(w, drainRetryAfterSeconds*time.Second)
			writeError(w, r, http.StatusServiceUnavailable, errCodeDraining)
			return
		}
		if err != nil {
			logger.Error("retrieval failed",
				"err", err, "workspace_id", req.WorkspaceID, "workspaces", wsSet,
				"user_id", userID, "request_id", requestIDOf(ctx), queryLogAttr(req.Message))
			writeError(w, r, http.StatusBadGateway, errCodeRetrieval)
			return
		}

		// (2) Ensure a conversation, load server-side memory, persist the USER turn.
		// History comes from the DB (authoritative memory that survives across
		// turns and works for the widget too). Client-sent history only seeds
		// an internal conversation's first turn (and the no-DB hot-path mode),
		// reduced to plain user/assistant turns so it cannot forge a system or
		// tool message. Widget sessions ignore it: their history is the
		// server-stored conversation bound to the token's session id.
		//
		// A client-supplied conversation id is resumed only if it belongs to this
		// workspace AND this principal (user, or widget session). Otherwise it is
		// silently replaced by a fresh conversation, so a leaked/guessed id can
		// neither read another thread's history nor append to it, and the
		// response does not reveal whether the id exists.
		convID := req.ConversationID
		var history []ports.Message
		if !widgetSession {
			history = sanitizeClientHistory(req.History, cfg.HistoryMaxMessages)
		}
		turn := botTurn{}
		if resuming {
			convID = resume.ConversationID
			turn = botTurn{conversationID: convID, messageID: req.ResumeMessageID}
			// History without the trailing user turn: it is re-sent as the question.
			if h, e := deps.Store.RecentMessages(ctx, convID, cfg.HistoryMaxMessages+1); e != nil {
				logger.Error("load history", "err", e)
			} else {
				if n := len(h); n > 0 && h[n-1].Role == ports.RoleUser && h[n-1].Content == req.Message {
					h = h[:n-1]
				}
				history = h
			}
		} else if deps.Store != nil {
			if convID != "" {
				owned, e := deps.Store.OwnsConversation(ctx, convID, req.WorkspaceID, userID, sessionKey)
				if e != nil {
					logger.Error("conversation ownership check", "err", e, "request_id", requestIDOf(ctx))
				}
				if e != nil || !owned {
					convID = ""
				}
			}
			if convID == "" {
				if id, e := deps.Store.EnsureConversation(ctx, req.WorkspaceID, userID, sessionKey); e != nil {
					logger.Error("ensure conversation", "err", e)
				} else {
					convID = id
				}
			}
			if convID != "" {
				// Load prior turns BEFORE persisting the current one.
				if h, e := deps.Store.RecentMessages(ctx, convID, cfg.HistoryMaxMessages); e != nil {
					logger.Error("load history", "err", e)
				} else if len(h) > 0 {
					history = h
				}
				if _, e := deps.Store.InsertMessage(ctx, convID, "USER", req.Message, 0, "", false); e != nil {
					logger.Error("persist user message", "err", e)
				}
				// Reserve the assistant row now so the client learns its id up front.
				turn.conversationID = convID
				if id, e := deps.Store.CreateBotPlaceholder(ctx, convID); e != nil {
					logger.Error("reserve bot message", "err", e)
				} else {
					turn.messageID = id
					preStreamCleanup = func() {
						if err := deps.Store.DeleteBotPlaceholder(context.Background(), id); err != nil {
							logger.Error("discard bot placeholder", "err", err)
						}
					}
				}
			}
		}

		// Per-workspace chat-intelligence flags (one lookup, reused below).
		feats := deps.workspaceFeatures(ctx, req.WorkspaceID)

		// Personalization (opt-in, INTERNAL authenticated chats only): inject the
		// asker's profile so answers can adapt to who is asking. Gated by the global
		// kill-switch AND the per-workspace flag; anonymous widget sessions (empty
		// userID) are structurally never personalized. Fail-soft.
		persona := ""
		if cfg.PersonalizationEnabled && userID != "" && feats.Personalization && deps.Store != nil {
			if p, perr := deps.Store.GetUserPersona(ctx, userID); perr == nil {
				persona = p.Block(loc)
			}
		}

		// Durable memory (opt-in): prepend short facts the assistant learned about
		// this user in earlier chats, so a fresh conversation already knows them.
		// The block goes to the external LLM, hence the double gate (global kill
		// switch + per-workspace flag) and authenticated users only.
		if memoryAllowed(cfg, feats, userID, deps) {
			if facts, merr := deps.memoryStore().GetUserMemory(ctx, userID, 20); merr == nil && len(facts) > 0 {
				mem := memoryBlock(loc, facts)
				if persona == "" {
					persona = mem
				} else {
					persona += "\n\n" + mem
				}
			}
		}

		// Web-search fallback (Brave, opt-in). When the user confirmed web search
		// (req.WebSearch) we run it and answer from the web; otherwise, when the
		// documents didn't cover the question, we OFFER it (client shows a button).
		// Gated by the global kill-switch AND the per-workspace flag. Fail-open: a
		// Brave error leaves us on the documents path.
		//
		// Deep research (req.DeepSearch) shares the SAME gates as web search. When
		// it is requested AND the gates pass, the DEEP pipeline takes precedence
		// over the single-web path (decompose -> search each -> dedup -> synthesise)
		// and runs AFTER the SSE stream opens (so it can emit deep_progress). When
		// it is requested but the gates are OFF, we emit web_unavailable below and
		// fall back to the normal documents answer (never hard-fail).
		webGated := webSearchGated(cfg, deps, feats, widgetSession)
		useDeep := req.DeepSearch && webGated && allowed(req.AllowTools, "deep_research")
		webOffer := ""
		var webResults []ports.WebResult
		useWeb := false
		if webGated && !useDeep {
			if req.WebSearch && allowed(req.AllowTools, "web_search") {
				query := generateWebQuery(ctx, deps, logger, req.Model, req.Message)
				if rs := singleWebResearch(ctx, deps, logger, cfg, req.Message, query); len(rs) > 0 {
					webResults = rs
					useWeb = true
				}
			} else if strings.TrimSpace(res.ContextText) == "" {
				webOffer = "empty"
			} else if res.LowConfidence {
				webOffer = "low_confidence"
			}
		}

		// attachVision attaches client images to the final user turn IF the model
		// supports them (VISION_MODELS); otherwise it drops them and appends a short
		// note so the model — and the user — know the image was ignored (graceful,
		// no upstream 4xx). Shared by the pre-SSE (documents/single-web) and post-SSE
		// (deep) message-assembly branches.
		attachVision := func(msgs []ports.Message) {
			if len(req.Attachments) == 0 || len(msgs) == 0 {
				return
			}
			last := &msgs[len(msgs)-1]
			if cfg.SupportsVision(req.Model) {
				parts := []ports.ContentPart{{Type: "text", Text: last.Content}}
				n := 0
				for _, a := range req.Attachments {
					if !validAttachment(a) { // already enforced at decode; kept as a guard
						continue
					}
					parts = append(parts, ports.ContentPart{
						Type: "image_url", ImageURL: &ports.ImageURLPart{URL: a.DataURL},
					})
					if n++; n >= maxAttachments {
						break
					}
				}
				if n > 0 {
					last.Parts = parts
				}
			} else {
				last.Content += locale.Pick(visionDropNote, loc)
			}
		}

		// Resolve the reasoning effort (CoT depth) once: a valid per-request value
		// wins, else the config default. Passed into every chat path below.
		effort := config.SanitizeReasoningEffort(strings.ToLower(strings.TrimSpace(req.ReasoningEffort)))
		if effort == "" {
			effort = cfg.ReasoningEffort
		}
		if !cfg.SupportsReasoning(req.Model) {
			effort = ""
		}

		// The Jira gate comes from JiraGate when set, else the Store (production).
		var jiraGate JiraGatePort
		if deps.JiraGate != nil {
			jiraGate = deps.JiraGate
		} else if deps.Store != nil {
			jiraGate = deps.Store
		}

		// ── UNIFIED AGENTIC TURN (flag-gated) ─────────────────────────────────────
		// When AGENT_UNIFIED_LOOP is on, RAG documents are always-on grounding and
		// web/deep/MCP become tools seeded from the per-turn request flags, all run
		// through one agent.Run loop. With no tool enabled this is exactly ONE
		// Stream call — pure documents RAG, identical to the legacy path. When the
		// flag is OFF the entire block is skipped and the legacy three-branch code
		// below runs byte-for-byte as before.
		if cfg.AgentUnifiedLoop {
			preStreamCleanup = func() {} // the unified turn always finalizes the row
			runUnifiedTurn(w, r, cfg, deps, logger, req, unifiedTurnState{
				userID:   userID,
				widget:   widgetSession,
				convID:   convID,
				turn:     turn,
				history:  history,
				res:      res,
				feats:    feats,
				persona:  persona,
				effort:   effort,
				jiraGate: jiraGate,
				attach:   attachVision,
				locale:   loc,
			})
			return
		}

		// MCP tool-use (Phase 1: Jira READ tools). Only the DOCUMENTS path offers
		// tools for the MVP (web/deep are unchanged). Gated by the global flag
		// (deps.MCP != nil), the documents path, AND a connected `jira` integration
		// for this workspace's org. Fail-soft at every step: any error logs and
		// proceeds WITHOUT tools, so the chat is never broken by MCP. When tools end
		// up unused, every line below behaves exactly as before.
		//
		// MCP tools act with the ORG's integration credentials, so they are offered
		// only to an authenticated INTERNAL user (userID is set solely from a
		// verified aud=admin token). Widget sessions and the unauthenticated
		// hot-path mode never get them, whatever the request asks for.
		mcpReg := agent.NewRegistry()
		useTools := false
		if mcpPermitted(userID) && req.MCPTools && allowed(req.AllowTools, "mcp") &&
			deps.MCP != nil && !useDeep && !useWeb && jiraGate != nil {
			if !cfg.SupportsTools(req.Model) {
				logger.Warn("model does not support tool-calling; skipping MCP tools", "model", req.Model, "workspace_id", req.WorkspaceID)
			} else if has, herr := jiraGate.HasConnectedJira(ctx, req.WorkspaceID); herr != nil {
				logger.Warn("jira integration check failed; proceeding without tools", "err", herr, "workspace_id", req.WorkspaceID)
			} else if has {
				if defs, lerr := deps.MCP.ListTools(ctx); lerr != nil {
					logger.Warn("mcp tools/list failed; proceeding without tools", "err", lerr)
				} else {
					addMCPTools(mcpReg, deps.MCP, defs, req.AllowTools, cfg.MCPAllowWriteTools, req.Message)
					useTools = !mcpReg.Empty()
				}
			}
		}

		// (3) For the documents and single-web paths, build the prompt and START the
		// chat stream (which may shed) BEFORE opening the SSE response, so a 503 is a
		// clean pre-stream JSON error. The DEEP path defers this to after SSE opens
		// (it must emit deep_progress first), so it is skipped here. The TOOLS path
		// likewise defers its first Stream call (it must emit tool_call/tool_result
		// events and may loop), so it is skipped here too.
		var msgs []ports.Message
		var stream <-chan ports.ChatChunk
		if !useDeep && !useTools {
			if useWeb {
				msgs = deps.RAG.AssembleWebMessages(req.SystemPrompt, history, webEvidenceContextBlock(webResults), req.Message, cfg.HistoryMaxMessages, persona, req.AnswerStyle, loc)
			} else {
				msgs = deps.RAG.AssembleMessages(req.SystemPrompt, history, res.ContextText, req.Message, cfg.HistoryMaxMessages, res.LowConfidence, persona, req.AnswerStyle, loc)
			}
			attachVision(msgs)
			var serr error
			stream, serr = deps.Chat.Stream(ctx, ports.ChatRequest{Messages: msgs, Temperature: req.Temperature, Model: req.Model, ReasoningEffort: effort})
			if errors.Is(serr, llm.ErrUpstreamBusy) {
				shed(w, r)
				return
			}
			if serr != nil {
				logger.Error("chat upstream failed",
					"err", serr, "workspace_id", req.WorkspaceID, "user_id", userID,
					"request_id", requestIDOf(ctx), "model", req.Model, queryLogAttr(req.Message))
				writeError(w, r, http.StatusBadGateway, errCodeUpstream)
				return
			}
		} else if useTools {
			// Build the documents prompt now (cheap) so the agentic loop can seed its
			// message list; the Stream call itself runs after SSE opens.
			msgs = deps.RAG.AssembleMessages(req.SystemPrompt, history, res.ContextText, req.Message, cfg.HistoryMaxMessages, res.LowConfidence, persona, req.AnswerStyle, loc)
			attachVision(msgs)
		}

		// (4) Stream SSE.
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

		preStreamCleanup = func() {} // streaming started: persistBotTurn sets the final state
		if turn.conversationID == "" {
			turn.conversationID = convID
		}
		writeMetaEvent(w, turn)
		flush()

		// DEEP pipeline (post-SSE so deep_progress can be emitted): decompose the
		// question into sub-queries, search each SEQUENTIALLY, dedup by URL, then
		// synthesise. On a hard failure (no results, or the synthesis stream can't
		// start) we fall back to the documents answer instead of hard-failing.
		if useDeep {
			// Status event BEFORE the (blocking, up-to-20s) sub-query generation so the
			// UI shows activity during the wait instead of a silent pause.
			fmt.Fprintf(w, "event: deep_progress\ndata: %s\n\n", mustJSON(map[string]string{"status": "generating_queries"}))
			flush()

			_, webResults := deepWebResearch(ctx, deps, logger, cfg, req.Model, req.Message, func(event string, data []byte) {
				fmt.Fprintf(w, "event: %s\ndata: %s\n\n", event, data)
				flush()
			})
			if len(webResults) == 0 {
				// No web results at all: tell the client (localized note) and fall
				// back to the normal documents answer.
				fmt.Fprintf(w, "event: web_unavailable\ndata: {}\n\n")
				flush()
				useDeep = false
				msgs = deps.RAG.AssembleMessages(req.SystemPrompt, history, res.ContextText, req.Message, cfg.HistoryMaxMessages, res.LowConfidence, persona, req.AnswerStyle, loc)
			} else {
				msgs = deps.RAG.AssembleDeepMessages(req.SystemPrompt, history, webEvidenceContextBlock(webResults), req.Message, cfg.HistoryMaxMessages, persona, req.AnswerStyle, loc)
			}
			fmt.Fprintf(w, "event: search_progress\ndata: %s\n\n", mustJSON(map[string]string{"status": "synthesizing"}))
			flush()
			attachVision(msgs)
			var serr error
			stream, serr = deps.Chat.Stream(ctx, ports.ChatRequest{Messages: msgs, Temperature: req.Temperature, Model: req.Model, ReasoningEffort: effort})
			if serr != nil {
				// Headers already sent — surface a graceful SSE error and stop. A shed
				// here also lands as a friendly stream error (status can't change now).
				logger.Error("deep synthesis upstream failed",
					"err", serr, "workspace_id", req.WorkspaceID, "user_id", userID,
					"request_id", requestIDOf(ctx), "model", req.Model, queryLogAttr(req.Message))
				if errors.Is(serr, llm.ErrUpstreamBusy) {
					writeStreamError(w, r, errCodeBusy)
				} else {
					writeStreamError(w, r, errCodeStream)
				}
				flush()
				fmt.Fprint(w, "data: [DONE]\n\n")
				flush()
				return
			}
		}

		var sourcesJSON []byte
		if useWeb || useDeep {
			sourcesJSON, _ = json.Marshal(webSourceCards(webResults))
		} else {
			sourcesJSON, _ = json.Marshal(res.Chunks)
		}
		fmt.Fprintf(w, "event: sources\ndata: {\"sources\":%s}\n\n", sourcesJSON)
		flush()

		// Offer a web search when the documents didn't cover the question (and the
		// user hasn't already opted in). The client renders a "search the web" button.
		if webOffer != "" {
			offer, _ := json.Marshal(map[string]string{"question": req.Message, "reason": webOffer})
			fmt.Fprintf(w, "event: web_offer\ndata: %s\n\n", offer)
			flush()
		}
		// The user toggled web (or deep) search on, but it's disabled for this
		// workspace — tell the client (which renders a localized note) instead of
		// silently ignoring it. The client knows the mode was on, so an empty payload
		// is enough. For deep search the gate may be off for any reason (!webGated),
		// so we fall back to the documents answer below. (The deep path that DID run
		// but found zero results already emitted web_unavailable above.)
		if cfg.WebSearchEnabled && deps.Web != nil && !feats.WebSearch && req.WebSearch {
			fmt.Fprintf(w, "event: web_unavailable\ndata: {}\n\n")
			flush()
		}
		if req.DeepSearch && !webGated {
			fmt.Fprintf(w, "event: web_unavailable\ndata: {}\n\n")
			flush()
		}

		var answer strings.Builder
		var usage *ports.Usage
		completed := false
		streamErrWritten := false // tools path already emitted an SSE error (don't double-emit)
		var toolExecutions []agent.ToolExecution

		// AGENTIC TOOL LOOP (MCP, documents path only). Legacy MCP now uses the
		// shared agent loop so validation, synthesized tool ids, audit summaries,
		// and stream-error handling stay identical to the unified path.
		if useTools {
			emit := func(event string, data []byte) {
				if event == "" {
					fmt.Fprintf(w, "data: %s\n\n", data)
				} else {
					fmt.Fprintf(w, "event: %s\ndata: %s\n\n", event, data)
				}
				flush()
			}
			result := agent.RunWithTools(ctx, mcpReg, agent.RunParams{
				Chat:                  deps.Chat,
				Messages:              msgs,
				Temperature:           req.Temperature,
				Model:                 req.Model,
				ReasoningEffort:       effort,
				ToolChoice:            "auto",
				MaxIterations:         cfg.MCPMaxIterations,
				IterLimitNote:         locale.Pick(iterLimitNote, loc),
				IterLimitThinkingNote: locale.Pick(iterLimitThinkingNote, loc),
				StreamReasoning:       cfg.StreamReasoning,
			}, emit)
			answer.WriteString(result.Answer)
			usage = result.Usage
			completed = result.Completed
			toolExecutions = result.ToolExecutions
			if result.Err != nil {
				logger.Error("chat upstream failed (tools)",
					"err", result.Err, "workspace_id", req.WorkspaceID, "user_id", userID,
					"request_id", requestIDOf(ctx), "model", req.Model, queryLogAttr(req.Message))
				if errors.Is(result.Err, llm.ErrUpstreamBusy) {
					writeStreamError(w, r, errCodeBusy)
				} else {
					writeStreamError(w, r, errCodeStream)
				}
				flush()
				streamErrWritten = true
			}
		} else {
			for chunk := range stream {
				if chunk.Err != nil {
					logger.Error("chat stream chunk error",
						"err", chunk.Err, "workspace_id", req.WorkspaceID, "user_id", userID,
						"request_id", requestIDOf(ctx), "model", req.Model, queryLogAttr(req.Message))
					break
				}
				if chunk.Done {
					completed = true
					usage = chunk.Usage
					break
				}
				// Reasoning (chain-of-thought) is relayed on a SEPARATE `thinking`
				// channel only when STREAM_REASONING is on, and is never persisted
				// with the answer. It arrives before (and may interleave with) the
				// answer content.
				if chunk.Reasoning != "" {
					if cfg.StreamReasoning {
						data, _ := json.Marshal(map[string]string{"delta": chunk.Reasoning})
						fmt.Fprintf(w, "event: thinking\ndata: %s\n\n", data)
						flush()
					}
					continue
				}
				answer.WriteString(chunk.Delta)
				data, _ := json.Marshal(map[string]string{"delta": chunk.Delta})
				fmt.Fprintf(w, "data: %s\n\n", data)
				flush()
			}
		}
		// Mid-stream failure: the provider closed the stream without a terminal Done
		// chunk while the CLIENT is still connected (a client abort cancels ctx and we
		// stay silent). Emit a graceful SSE error note so the UI shows a friendly
		// message instead of a truncated answer; status is already 200 (headers sent).
		// The tools loop may have already emitted its own SSE error — don't double it.
		if !completed && ctx.Err() == nil && !streamErrWritten {
			logger.Error("chat stream ended without completion",
				"workspace_id", req.WorkspaceID, "user_id", userID,
				"request_id", requestIDOf(ctx), "model", req.Model, queryLogAttr(req.Message))
			writeStreamError(w, r, errCodeStream)
			flush()
		}
		// (5) Persist the BOT turn (partial if aborted) BEFORE the final markers so
		// we can hand the client its message id (for 👍/👎 feedback) + emit
		// chat.completed only on full completion. Fresh context: a client disconnect
		// mid-flush mustn't lose what we already produced.
		usedTokens := 0
		if usage != nil {
			usedTokens = usage.CompletionTokens
		}
		botMsgID := persistBotTurn(ctx, deps, logger, turn, req.WorkspaceID, answer.String(), usedTokens,
			string(sourcesJSON), completed, withToolAudit(requestMessageAudit(req), toolExecutions))

		// Hand the client the BOT message id so it can attach feedback to this turn.
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

		// (6) Durable memory extraction (opt-in, authenticated INTERNAL chats only).
		// Runs AFTER the response in the background so it never slows the answer.
		if completed && memoryAllowed(cfg, feats, userID, deps) && deps.Chat != nil {
			scheduleMemoryExtraction(deps, logger, loc, userID, req.Model, req.Message, answer.String())
		}
	}
}

// sessionKeyLimit returns the per-widget-session limit, or 0 (skip) for legacy
// tokens without a session id — those are still covered by the per-IP limit.
func sessionKeyLimit(cfg config.Config, sid string) int {
	if sid == "" {
		return 0
	}
	return cfg.RateLimitChatWidgetSessionPerMinute
}

// requestedWorkspaces returns the de-duplicated union of the primary workspace
// and the search set, so authorization can never skip either.
func requestedWorkspaces(primary string, set []string) []string {
	out := make([]string, 0, len(set)+1)
	seen := make(map[string]bool, len(set)+1)
	for _, ws := range append([]string{primary}, set...) {
		if !seen[ws] {
			seen[ws] = true
			out = append(out, ws)
		}
	}
	return out
}

func scheduleMemoryExtraction(
	deps Deps,
	logger *slog.Logger,
	loc locale.Locale,
	userID, model, userMsg, botMsg string,
) {
	if deps.Background == nil {
		return
	}
	deps.Background.TryGo("memory_extraction", func(ctx context.Context) {
		extractAndStoreMemory(ctx, deps, logger, loc, userID, model, userMsg, botMsg)
	})
}

// extractAndStoreMemory runs one cheap completion to mine durable user facts from
// the latest exchange and upserts them. Best-effort: any error is dropped.
func extractAndStoreMemory(
	ctx context.Context,
	deps Deps,
	logger *slog.Logger,
	loc locale.Locale,
	userID, model, userMsg, botMsg string,
) {
	defer func() {
		if r := recover(); r != nil {
			logger.Error("memory extraction panicked", "err", r)
		}
	}()

	labels := locale.Pick(memoryTranscriptLabels, loc)
	msgs := []ports.Message{
		{Role: ports.RoleSystem, Content: locale.Pick(memoryExtractionPrompt, loc)},
		{Role: ports.RoleUser, Content: labels[0] + userMsg + "\n\n" + labels[1] + botMsg},
	}
	stream, err := deps.Chat.Stream(ctx, ports.ChatRequest{
		Messages: msgs, Model: model, Temperature: 0, MaxTokens: 256,
	})
	if err != nil {
		return // shed or upstream error — skip silently
	}
	var b strings.Builder
	for chunk := range stream {
		if chunk.Err != nil {
			return
		}
		if chunk.Done {
			break
		}
		b.WriteString(chunk.Delta)
	}
	facts := parseMemoryFacts(b.String())
	if len(facts) == 0 {
		return
	}
	mem := deps.memoryStore()
	if mem == nil {
		return
	}
	if err := mem.AddUserMemory(ctx, userID, facts); err != nil {
		logger.Error("store user memory", "err", err)
	}
}

// parseMemoryFacts turns the extraction output into clean, deduped fact lines.
func parseMemoryFacts(raw string) []string {
	out := []string{}
	seen := map[string]bool{}
	for _, line := range strings.Split(raw, "\n") {
		f := strings.TrimSpace(line)
		f = strings.TrimLeft(f, "-*•0123456789. \t")
		if f == "" || strings.EqualFold(f, "NONE") || len([]rune(f)) > 200 {
			continue
		}
		if seen[f] {
			continue
		}
		seen[f] = true
		out = append(out, f)
		if len(out) >= 8 { // cap facts per turn
			break
		}
	}
	return out
}

// webContextBlock renders web results as the labeled [n] context fed to the
// web/deep synthesis prompts. The label order MUST match the order results are
// emitted in the SSE `sources` event so [n] citations line up with the cards.
func webContextBlock(results []ports.WebResult) string {
	var wb strings.Builder
	for i, wr := range results {
		title := wr.Title
		if title == "" {
			title = wr.URL
		}
		fmt.Fprintf(&wb, "[%d] (source: %s — %s)\n%s\n\n", i+1, title, wr.URL, wr.Snippet)
	}
	return wb.String()
}

// generateSubQueries runs ONE cheap completion (T=0, small max_tokens — same
// pattern as extractAndStoreMemory) to decompose the question into focused
// web-search queries. It always includes the original question, trims/cleans the
// model's lines, drops empties + dupes, and caps at maxQueries. On any failure or
// empty output it falls back to just [question] (graceful). Uses the chat pool
// like every other completion; acquire/release is handled inside Stream.
func generateSubQueries(
	ctx context.Context,
	deps Deps,
	logger *slog.Logger,
	model, question string,
	maxQueries int,
) []string {
	if maxQueries <= 0 {
		maxQueries = 6
	}
	fallback := []string{question}

	genCtx, cancel := context.WithTimeout(ctx, 20*time.Second)
	defer cancel()
	msgs := []ports.Message{
		{Role: ports.RoleSystem, Content: locale.Pick(subQueryPrompt, requestLocale(ctx))},
		{Role: ports.RoleUser, Content: question},
	}
	stream, err := deps.Chat.Stream(genCtx, ports.ChatRequest{
		Messages: msgs, Model: model, Temperature: 0, MaxTokens: 256,
	})
	if err != nil {
		if logger != nil {
			logger.Warn("deep sub-query generation failed; using original question only", "err", err)
		}
		return fallback
	}
	var b strings.Builder
	for chunk := range stream { // drain fully so the pool slot is released
		if chunk.Err != nil {
			return fallback
		}
		if chunk.Done {
			break
		}
		b.WriteString(chunk.Delta)
	}
	return parseSubQueries(b.String(), question, maxQueries)
}

// generateWebQuery runs ONE cheap completion (T=0, small max_tokens — same pattern
// as generateSubQueries) to reformulate a user message into a single focused web
// search query. On ANY error or empty output it falls back to the raw message
// (graceful). Uses the chat pool like every other completion; acquire/release is
// handled inside Stream.
func generateWebQuery(
	ctx context.Context,
	deps Deps,
	logger *slog.Logger,
	model, message string,
) string {
	fallback := strings.TrimSpace(message)

	genCtx, cancel := context.WithTimeout(ctx, 20*time.Second)
	defer cancel()
	msgs := []ports.Message{
		{Role: ports.RoleSystem, Content: locale.Pick(webQueryPrompt, requestLocale(ctx))},
		{Role: ports.RoleUser, Content: message},
	}
	stream, err := deps.Chat.Stream(genCtx, ports.ChatRequest{
		Messages: msgs, Model: model, Temperature: 0, MaxTokens: 128,
	})
	if err != nil {
		if logger != nil {
			logger.Warn("web query reformulation failed; using raw message", "err", err)
		}
		return fallback
	}
	var b strings.Builder
	for chunk := range stream { // drain fully so the pool slot is released
		if chunk.Err != nil {
			return fallback
		}
		if chunk.Done {
			break
		}
		b.WriteString(chunk.Delta)
	}
	return cleanGeneratedWebQuery(b.String(), fallback)
}

// cleanGeneratedWebQuery accepts the plain-text format requested by the prompt,
// while also tolerating common provider deviations such as {"query":"..."} or
// {"queries":["..."]}. Sending the JSON wrapper itself to Brave materially hurts
// recall, so only the extracted query text may leave the edge.
func cleanGeneratedWebQuery(raw, fallback string) string {
	type queryEnvelope struct {
		Query   string   `json:"query"`
		Queries []string `json:"queries"`
	}
	if obj := extractJSONObject(raw); obj != "" {
		var envelope queryEnvelope
		if json.Unmarshal([]byte(obj), &envelope) == nil {
			if q := cleanSingleWebQuery(envelope.Query); q != "" {
				return q
			}
			for _, candidate := range envelope.Queries {
				if q := cleanSingleWebQuery(candidate); q != "" {
					return q
				}
			}
		}
	}

	// Take the first non-empty line, strip bullets/quotes the same way sub-queries
	// are cleaned, and fall back to the raw message if nothing usable came back.
	for _, line := range strings.Split(raw, "\n") {
		if q := cleanSingleWebQuery(line); q != "" {
			return q
		}
	}
	return fallback
}

func cleanSingleWebQuery(query string) string {
	q := strings.TrimSpace(query)
	lower := strings.ToLower(q)
	if colon := strings.Index(q, ":"); colon >= 0 && colon < 32 &&
		strings.Contains(lower[:colon], "query") {
		q = q[colon+1:]
	}
	q = strings.TrimLeft(q, "-*•0123456789.)( \t")
	q = strings.Trim(q, "\"'`{}[] \t\r\n")
	q = strings.TrimSuffix(q, ",")
	q = strings.Trim(q, "\"'`{}[] \t\r\n")
	if q == "" || len([]rune(q)) > 300 {
		return ""
	}
	return q
}

// parseSubQueries cleans the generation output into a deduped query list, ALWAYS
// including the original question (first), and caps the total at maxQueries.
func parseSubQueries(raw, question string, maxQueries int) []string {
	out := make([]string, 0, maxQueries)
	seen := map[string]bool{}
	// add appends a cleaned query if it is non-empty and unseen. Empties/dupes are
	// silently skipped (NOT treated as "stop"); the caller stops only once the cap
	// is reached.
	add := func(q string) {
		q = strings.TrimSpace(q)
		if q == "" {
			return
		}
		key := strings.ToLower(q)
		if seen[key] {
			return
		}
		seen[key] = true
		out = append(out, q)
	}
	// The original question always goes first so it is never dropped by the cap.
	add(question)
	for _, line := range strings.Split(raw, "\n") {
		if len(out) >= maxQueries {
			break
		}
		q := strings.TrimSpace(line)
		q = strings.TrimLeft(q, "-*•0123456789.)( \t")
		q = strings.Trim(q, "\"'`")
		if len([]rune(q)) > 300 {
			continue
		}
		add(q)
	}
	return out
}

// deepSearch runs each query through Brave SEQUENTIALLY (Brave's free tier
// rate-limits, so we deliberately do NOT fan out in parallel), collects the hits,
// DEDUPES by URL, and caps the total at maxResults (cfg.DeepSearchMaxResults). A
// per-query error is non-fatal (logged, then we continue). The returned order is
// the discovery order across queries, which the caller mirrors in the context
// labels and the SSE `sources` event so [n] citations line up.
func deepSearch(ctx context.Context, deps Deps, logger *slog.Logger, queries []string, topN, maxResults int) []ports.WebResult {
	if maxResults <= 0 {
		maxResults = 50
	}
	out := make([]ports.WebResult, 0, maxResults)
	seen := map[string]bool{}
	for _, q := range queries {
		if ctx.Err() != nil { // client gone — stop early
			break
		}
		rs, err := deps.Web.Search(ctx, q, topN)
		if err != nil {
			if logger != nil {
				logger.Warn("deep sub-query search failed; continuing", "err", err, queryLogAttr(q))
			}
			continue
		}
		for _, r := range rs {
			if r.URL == "" || seen[r.URL] {
				continue
			}
			seen[r.URL] = true
			out = append(out, r)
			if len(out) >= maxResults {
				return out
			}
		}
	}
	return out
}

// requestIDOf returns the X-Request-Id stamped by the requestID middleware (for
// correlating a failing query in logs), or "" when absent.
func requestIDOf(ctx context.Context) string {
	id, _ := ctx.Value(requestIDKey).(string)
	return id
}

// queryLogAttr describes user-supplied text (a chat message, task prompt or
// web query) for logs WITHOUT its content: only the length and a short SHA-256
// prefix, which is enough to correlate repeated failures of the same input.
// Prompts routinely carry personal data, so their text never reaches logs.
func queryLogAttr(s string) slog.Attr {
	sum := sha256.Sum256([]byte(s))
	return slog.Group("query", "len", len(s), "sha256", hex.EncodeToString(sum[:6]))
}

// truncPreview clips a tool result to a short, rune-safe preview for the live
// tool_result SSE event (the FULL result still goes back to the model). Bounds by
// runes so multibyte (Turkish/Jira) text is never cut mid-character.
func truncPreview(s string, max int) string {
	r := []rune(s)
	if len(r) <= max {
		return s
	}
	return string(r[:max]) + "…"
}

// mustJSON marshals v to a JSON byte slice, ignoring the (impossible for these
// map[string]string payloads) error — a tiny helper for inline SSE writes.
func mustJSON(v any) []byte {
	b, _ := json.Marshal(v)
	return b
}

// shed responds when the bounded outbound pool is saturated (A5 ceiling). It is
// always called PRE-STREAM, so it returns the friendly JSON error contract with a
// Retry-After hint.
func shed(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Retry-After", "1")
	writeError(w, r, http.StatusServiceUnavailable, errCodeBusy)
}
