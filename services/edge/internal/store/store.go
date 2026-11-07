// SPDX-License-Identifier: Apache-2.0

// Package store persists conversations and messages for the edge (pgx).
package store

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"regexp"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/alicangunduz/raggie/services/edge/internal/locale"
	"github.com/alicangunduz/raggie/services/edge/internal/ports"
)

type Store struct {
	pool *pgxpool.Pool
}

func New(ctx context.Context, dsn string) (*Store, error) {
	pool, err := pgxpool.New(ctx, dsn)
	if err != nil {
		return nil, err
	}
	if err := pool.Ping(ctx); err != nil {
		pool.Close()
		return nil, err
	}
	return &Store{pool: pool}, nil
}

func (s *Store) Close() { s.pool.Close() }

func (s *Store) Ready(ctx context.Context) error { return s.pool.Ping(ctx) }

// WorkspaceWidget returns the type, CORS allow-list, widget primary color, and
// name for a workspace. Used by the edge to enforce A4 (EXTERNAL-only widget
// tokens + per-workspace CORS). Returns an error if the workspace is unknown.
func (s *Store) WorkspaceWidget(
	ctx context.Context, workspaceID string,
) (typ string, corsOrigins []string, primaryColor, name string, err error) {
	err = s.pool.QueryRow(ctx,
		"SELECT type, cors_allowed_origins, widget_primary_color, name"+
			" FROM workspaces WHERE id = $1::uuid",
		workspaceID,
	).Scan(&typ, &corsOrigins, &primaryColor, &name)
	return typ, corsOrigins, primaryColor, name, err
}

// WorkspaceFeatureFlags are the per-workspace chat-intelligence toggles. Each
// is the per-workspace half of a double gate; the global kill switch (env) is
// checked by the caller.
type WorkspaceFeatureFlags struct {
	WebSearch       bool
	Personalization bool
	Memory          bool // durable per-user memory (workspaces.memory_enabled, migration 0027)
}

// ResolvedSkill is the immutable, currently-active execution-policy snapshot
// selected for a chat turn. The edge never accepts these fields from a client.
type ResolvedSkill struct {
	ID           string
	Version      int
	PolicyHash   string
	Instructions string
	Model        string
	AnswerStyle  string
	AllowedTools []string
}

// ChatPolicy is the trusted workspace + optional skill policy for one turn.
type ChatPolicy struct {
	WorkspaceSystemPrompt string
	WorkspaceTemperature  float32
	AllowedModels         []string
	Skill                 *ResolvedSkill
}

// ResolveChatPolicy loads workspace defaults and, when requested, the current
// immutable skill snapshot. Old versions are deliberately not executable: this
// prevents a replayed client request from bypassing a later policy/tool change.
func (s *Store) ResolveChatPolicy(
	ctx context.Context,
	userID, workspaceID, skillID string,
	skillVersion int,
) (ChatPolicy, error) {
	var (
		policy        ChatPolicy
		allowedModels string
	)
	err := s.pool.QueryRow(ctx,
		"SELECT w.system_prompt, w.temperature,"+
			" COALESCE(ss.chat_allowed_models, '[]'::jsonb)::text"+
			" FROM workspaces w"+
			" LEFT JOIN system_settings ss ON ss.id = 'current'"+
			" WHERE w.id = $1::uuid",
		workspaceID,
	).Scan(
		&policy.WorkspaceSystemPrompt,
		&policy.WorkspaceTemperature,
		&allowedModels,
	)
	if err != nil {
		return ChatPolicy{}, err
	}
	policy.AllowedModels, err = decodeStringListJSON(allowedModels)
	if err != nil {
		return ChatPolicy{}, fmt.Errorf("decode allowed models: %w", err)
	}

	if skillID == "" {
		return policy, nil
	}
	if userID == "" || skillVersion < 1 {
		return ChatPolicy{}, pgx.ErrNoRows
	}

	resolved := ResolvedSkill{AllowedTools: make([]string, 0)}
	err = s.pool.QueryRow(ctx,
		"SELECT sv.skill_id::text, sv.version, sv.policy_hash, sv.instructions,"+
			" COALESCE(sv.model, ''), COALESCE(sv.answer_style, ''), sv.allowed_tools"+
			" FROM workspaces w"+
			" JOIN skills s ON s.org_id = w.org_id"+
			" JOIN skill_versions sv ON sv.skill_id = s.id AND sv.version = s.version"+
			" WHERE w.id = $1::uuid AND s.id = $2::uuid"+
			"   AND s.version = $3 AND s.enabled = TRUE"+
			"   AND ((s.owner_user_id IS NULL AND s.visibility = 'org')"+
			"        OR s.owner_user_id = $4::uuid)",
		workspaceID,
		skillID,
		skillVersion,
		userID,
	).Scan(
		&resolved.ID,
		&resolved.Version,
		&resolved.PolicyHash,
		&resolved.Instructions,
		&resolved.Model,
		&resolved.AnswerStyle,
		&resolved.AllowedTools,
	)
	if err != nil {
		return ChatPolicy{}, err
	}
	if resolved.AllowedTools == nil {
		resolved.AllowedTools = make([]string, 0)
	}
	policy.Skill = &resolved
	return policy, nil
}

func decodeStringListJSON(raw string) ([]string, error) {
	var value any
	if err := json.Unmarshal([]byte(raw), &value); err != nil {
		return nil, err
	}
	// Older control-plane builds double-encoded JSONB values. Accept one legacy
	// string layer so a malformed singleton setting cannot take chat offline.
	if encoded, ok := value.(string); ok {
		if err := json.Unmarshal([]byte(encoded), &value); err != nil {
			return nil, err
		}
	}
	items, ok := value.([]any)
	if !ok {
		return nil, fmt.Errorf("expected JSON string array, got %T", value)
	}
	out := make([]string, 0, len(items))
	for _, item := range items {
		text, ok := item.(string)
		if !ok {
			return nil, fmt.Errorf("expected string item, got %T", item)
		}
		out = append(out, text)
	}
	return out, nil
}

// WorkspaceFeatures reads the per-workspace web-search / personalization /
// memory flags. Against a schema older than control-plane migration 0027 (no
// memory_enabled column) it falls back to the two older flags with Memory
// false, so memory fails closed while web search and personalization keep
// working during a rolling upgrade.
func (s *Store) WorkspaceFeatures(ctx context.Context, workspaceID string) (WorkspaceFeatureFlags, error) {
	var f WorkspaceFeatureFlags
	err := s.pool.QueryRow(ctx,
		"SELECT web_search_enabled, personalization_enabled, memory_enabled FROM workspaces WHERE id = $1::uuid",
		workspaceID,
	).Scan(&f.WebSearch, &f.Personalization, &f.Memory)
	if isUndefinedColumn(err) {
		f = WorkspaceFeatureFlags{}
		err = s.pool.QueryRow(ctx,
			"SELECT web_search_enabled, personalization_enabled FROM workspaces WHERE id = $1::uuid",
			workspaceID,
		).Scan(&f.WebSearch, &f.Personalization)
	}
	if err != nil {
		f.Memory = false
	}
	return f, err
}

// isUndefinedColumn reports a Postgres undefined_column error (SQLSTATE 42703).
func isUndefinedColumn(err error) bool {
	var pgErr *pgconn.PgError
	return errors.As(err, &pgErr) && pgErr.Code == "42703"
}

// Persona is the asker's profile, summarised for the prompt when personalization
// is enabled. All fields optional; an empty persona produces an empty Block().
type Persona struct {
	FullName   string
	JobTitle   string
	Department string
	Manager    string
	Locale     string
	HireDate   *time.Time
}

// GetUserPersona loads the profile of an authenticated user (resolving the
// manager to a display name). Fail-soft: callers treat any error as "no persona".
func (s *Store) GetUserPersona(ctx context.Context, userID string) (Persona, error) {
	var (
		p    Persona
		hire *time.Time
		mgr  *string
	)
	err := s.pool.QueryRow(ctx,
		"SELECT COALESCE(u.full_name, ''), COALESCE(u.job_title, ''),"+
			" COALESCE(u.department, ''), COALESCE(u.locale, ''), u.hire_date,"+
			" (SELECT COALESCE(m.full_name, m.email) FROM users m WHERE m.id = u.manager_user_id)"+
			" FROM users u WHERE u.id = $1::uuid",
		userID,
	).Scan(&p.FullName, &p.JobTitle, &p.Department, &p.Locale, &hire, &mgr)
	if err != nil {
		return Persona{}, err
	}
	p.HireDate = hire
	if mgr != nil {
		p.Manager = *mgr
	}
	return p, nil
}

// Block renders a one-line persona preamble (in loc) for the system prompt, or ""
// when nothing useful is known.
func (p Persona) Block(loc locale.Locale) string {
	l := locale.Pick(personaLabels, loc)
	var parts []string
	if p.FullName != "" {
		parts = append(parts, l.name+p.FullName)
	}
	if p.JobTitle != "" {
		parts = append(parts, l.title+p.JobTitle)
	}
	if p.Department != "" {
		parts = append(parts, l.department+p.Department)
	}
	if p.Manager != "" {
		parts = append(parts, l.manager+p.Manager)
	}
	if p.HireDate != nil {
		days := int(time.Since(*p.HireDate).Hours() / 24)
		if days >= 365 {
			parts = append(parts, fmt.Sprintf(l.tenureYears, days/365))
		} else if days >= 0 {
			parts = append(parts, fmt.Sprintf(l.tenureDays, days))
		}
	}
	if len(parts) == 0 {
		return ""
	}
	return l.intro + strings.Join(parts, ", ") + "."
}

// personaLabels localizes the persona block (it is part of the system prompt).
type personaLabelSet struct {
	intro, name, title, department, manager, tenureYears, tenureDays string
}

var personaLabels = map[locale.Locale]personaLabelSet{
	locale.EN: {
		intro: "About the user (you may tailor the answer to this person; use this only to " +
			"personalize and do not repeat it unless asked): ",
		name: "Name: ", title: "Title: ", department: "Department: ", manager: "Manager: ",
		tenureYears: "Tenure: ~%d years", tenureDays: "Tenure: %d days",
	},
	locale.TR: {
		intro: "Kullanıcı hakkında (yanıtı bu kişiye göre uyarlayabilirsin; bu bilgiyi " +
			"yalnızca kişiselleştirmek için kullan, sorulmadıkça tekrarlama): ",
		name: "Ad: ", title: "Görev: ", department: "Departman: ", manager: "Yönetici: ",
		tenureYears: "Kıdem: ~%d yıl", tenureDays: "Kıdem: %d gün",
	},
}

// UserLocale returns an active user's stored UI language (users.locale).
func (s *Store) UserLocale(ctx context.Context, userID string) (string, error) {
	if !uuidPattern.MatchString(userID) {
		return "", pgx.ErrNoRows
	}
	var l string
	err := s.pool.QueryRow(ctx,
		"SELECT COALESCE(locale, '') FROM users WHERE id = $1::uuid AND is_active = TRUE", userID,
	).Scan(&l)
	return l, err
}

// EnsureConversation creates a conversation row and returns its id. userID ties
// the conversation to an authenticated user (so it shows in their history);
// session_token is for anonymous EXTERNAL widget sessions. Both are optional.
func (s *Store) EnsureConversation(ctx context.Context, workspaceID, userID, sessionToken string) (string, error) {
	var id string
	err := s.pool.QueryRow(ctx,
		"INSERT INTO conversations (workspace_id, user_id, session_token)"+
			" VALUES ($1::uuid, $2::uuid, $3) RETURNING id::text",
		workspaceID, nilIfEmpty(userID), nilIfEmpty(sessionToken),
	).Scan(&id)
	return id, err
}

// uuidPattern matches the canonical textual UUID form. Conversation ids from
// clients are validated before reaching a ::uuid cast.
var uuidPattern = regexp.MustCompile(
	`^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$`,
)

// OwnsConversation reports whether a client-supplied conversation id may be
// resumed by this caller: it must live in workspaceID AND belong to the caller
// — the authenticated user (userID) or, for anonymous widget chats, the
// server-issued widget session (sessionKey). With neither principal nothing is
// owned. Malformed ids are simply not owned (no error), so callers fall back
// to a fresh conversation without revealing whether the id exists.
func (s *Store) OwnsConversation(ctx context.Context, conversationID, workspaceID, userID, sessionKey string) (bool, error) {
	if !uuidPattern.MatchString(conversationID) || !uuidPattern.MatchString(workspaceID) {
		return false, nil
	}
	if userID == "" && sessionKey == "" {
		return false, nil
	}
	var ok bool
	err := s.pool.QueryRow(ctx,
		"SELECT EXISTS ("+
			" SELECT 1 FROM conversations"+
			" WHERE id = $1::uuid AND workspace_id = $2::uuid AND ("+
			"   ($3 <> '' AND user_id::text = $3)"+
			"   OR ($3 = '' AND $4 <> '' AND user_id IS NULL AND session_token = $4)"+
			" ))",
		conversationID, workspaceID, userID, sessionKey,
	).Scan(&ok)
	return ok, err
}

// UserOwnsConversation reports whether conversationID belongs to userID (the
// self-service history routes). Malformed ids are simply not owned.
func (s *Store) UserOwnsConversation(ctx context.Context, conversationID, userID string) (bool, error) {
	if !uuidPattern.MatchString(conversationID) || userID == "" {
		return false, nil
	}
	var ok bool
	err := s.pool.QueryRow(ctx,
		"SELECT EXISTS (SELECT 1 FROM conversations WHERE id = $1::uuid AND user_id::text = $2)",
		conversationID, userID,
	).Scan(&ok)
	return ok, err
}

// ConversationSummary is one entry in a user's chat history (title = first user
// message of the conversation).
type ConversationSummary struct {
	ID        string    `json:"id"`
	Title     string    `json:"title"`
	CreatedAt time.Time `json:"created_at"`
}

// ListConversations returns a user's most recent conversations (newest first),
// each titled by its first user message. Empty conversations are omitted.
func (s *Store) ListConversations(ctx context.Context, userID string, limit int) ([]ConversationSummary, error) {
	rows, err := s.pool.Query(ctx,
		"SELECT c.id::text,"+
			" COALESCE((SELECT m.content FROM messages m"+
			"   WHERE m.conversation_id = c.id AND m.sender = 'USER'"+
			"   ORDER BY m.created_at ASC LIMIT 1), '') AS title,"+
			" c.created_at"+
			" FROM conversations c"+
			" WHERE c.user_id = $1::uuid"+
			"   AND EXISTS (SELECT 1 FROM messages m2"+
			"     WHERE m2.conversation_id = c.id AND m2.sender = 'USER')"+
			" ORDER BY c.created_at DESC LIMIT $2",
		userID, limit,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []ConversationSummary
	for rows.Next() {
		var c ConversationSummary
		if err := rows.Scan(&c.ID, &c.Title, &c.CreatedAt); err != nil {
			return nil, err
		}
		out = append(out, c)
	}
	return out, rows.Err()
}

// DeleteConversation deletes one of the caller's conversations (and, via the
// messages.conversation_id ON DELETE CASCADE FK, all of its messages). The
// user_id predicate makes cross-user deletion impossible and skips anonymous
// widget conversations (null user_id). Returns ok=false if no row matched
// (unknown id or not owned by this user).
func (s *Store) DeleteConversation(ctx context.Context, conversationID, userID string) (bool, error) {
	if !uuidPattern.MatchString(conversationID) {
		return false, nil
	}
	tag, err := s.pool.Exec(ctx,
		"DELETE FROM conversations WHERE id = $1::uuid AND user_id = $2::uuid",
		conversationID, userID,
	)
	if err != nil {
		return false, err
	}
	return tag.RowsAffected() > 0, nil
}

// DeleteAllConversations deletes every conversation owned by the caller (and
// their messages, via the cascade). Anonymous widget conversations (null
// user_id) are untouched. Returns the number of conversations deleted.
func (s *Store) DeleteAllConversations(ctx context.Context, userID string) (int, error) {
	tag, err := s.pool.Exec(ctx,
		"DELETE FROM conversations WHERE user_id = $1::uuid",
		userID,
	)
	if err != nil {
		return 0, err
	}
	return int(tag.RowsAffected()), nil
}

// StoredMessage is a persisted turn for replay in the UI (sources is the raw
// JSON array string, or "").
type StoredMessage struct {
	Role    string `json:"role"`
	Content string `json:"content"`
	Sources string `json:"sources,omitempty"`
}

// ConversationMessages returns a conversation's completed turns in chronological
// order. The JOIN on user_id ensures a user can only read their own conversation.
func (s *Store) ConversationMessages(ctx context.Context, conversationID, userID string) ([]StoredMessage, error) {
	if !uuidPattern.MatchString(conversationID) {
		return nil, nil
	}
	rows, err := s.pool.Query(ctx,
		"SELECT m.sender, m.content, COALESCE(m.sources_json::text, '')"+
			" FROM messages m JOIN conversations c ON c.id = m.conversation_id"+
			" WHERE m.conversation_id = $1::uuid AND c.user_id = $2::uuid"+
			"   AND m.partial = false AND m.sender IN ('USER','BOT')"+
			" ORDER BY m.created_at ASC",
		conversationID, userID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []StoredMessage
	for rows.Next() {
		var sender, content, sources string
		if err := rows.Scan(&sender, &content, &sources); err != nil {
			return nil, err
		}
		role := ports.RoleUser
		if sender == "BOT" {
			role = ports.RoleAssistant
		}
		out = append(out, StoredMessage{Role: role, Content: content, Sources: sources})
	}
	return out, rows.Err()
}

// UserCanAccessWorkspace reports whether an ACTIVE user may use a workspace.
// Access is granted by, in order:
//   - users.is_platform_admin (the only cross-org authority),
//   - role SUPER_ADMIN, but only for workspaces of the user's own org,
//   - direct workspace membership, or membership in any team that is an
//     ancestor of the workspace's team (closure-table inheritance).
//
// The role is read from the database, never from the token, so a demotion or
// deactivation takes effect immediately. Mirrors the control-plane's
// effective-access resolution so the chat hot path enforces the same RBAC.
func (s *Store) UserCanAccessWorkspace(ctx context.Context, userID, workspaceID string) (bool, error) {
	var ok bool
	err := s.pool.QueryRow(ctx,
		"SELECT EXISTS ("+
			" SELECT 1 FROM users u JOIN workspaces w ON w.id = $2::uuid"+
			" WHERE u.id = $1::uuid AND u.is_active = TRUE AND ("+
			"   u.is_platform_admin"+
			"   OR (u.role = 'SUPER_ADMIN' AND u.org_id = w.org_id)"+
			"   OR w.id IN (SELECT workspace_id FROM workspace_members WHERE user_id = u.id)"+
			"   OR w.team_id IN ("+
			"     SELECT tc.descendant_id FROM team_closure tc"+
			"     JOIN team_members tm ON tm.team_id = tc.ancestor_id"+
			"     WHERE tm.user_id = u.id)"+
			" ))",
		userID, workspaceID,
	).Scan(&ok)
	return ok, err
}

// UserSessionActive validates the server-side session carried in an admin JWT.
// Joining users enforces SCIM/admin deactivation on every authenticated edge
// request.
func (s *Store) UserSessionActive(ctx context.Context, userID, sessionID string) (bool, error) {
	var ok bool
	err := s.pool.QueryRow(ctx,
		"SELECT EXISTS ("+
			" SELECT 1 FROM auth_sessions s"+
			" JOIN users u ON u.id = s.user_id"+
			" WHERE s.id = $2::uuid AND s.user_id = $1::uuid"+
			"   AND u.is_active = TRUE"+
			"   AND s.revoked_at IS NULL AND s.expires_at > now()"+
			")",
		userID, sessionID,
	).Scan(&ok)
	return ok, err
}

// InsertMessage stores one message and returns its id. sourcesJSON is a JSON
// array string (or "" for NULL); partial=true marks an aborted BOT stream.
func (s *Store) InsertMessage(
	ctx context.Context,
	conversationID, sender, content string,
	usedTokens int,
	sourcesJSON string,
	partial bool,
) (string, error) {
	return s.InsertMessageWithAudit(
		ctx,
		conversationID,
		sender,
		content,
		usedTokens,
		sourcesJSON,
		partial,
		MessageAudit{},
	)
}

// MessageAudit identifies the server-resolved execution policy used for a turn.
// Zero values are stored as NULL for non-BOT and non-skill messages.
type MessageAudit struct {
	SkillID         string
	SkillVersion    int
	SkillPolicyHash string
	ModelUsed       string
	ProviderUsed    string
	ToolCalls       []ToolCallAudit
}

// ToolCallAudit is a redacted execution summary for one model-requested tool
// call. It intentionally stores no raw arguments and no raw result content.
type ToolCallAudit struct {
	ID          string `json:"id,omitempty"`
	Name        string `json:"name"`
	Kind        string `json:"kind,omitempty"`
	OK          bool   `json:"ok"`
	LatencyMS   int64  `json:"latency_ms"`
	Error       string `json:"error,omitempty"`
	ArgsSHA256  string `json:"args_sha256,omitempty"`
	ResultChars int    `json:"result_chars"`
}

// InsertMessageWithAudit stores one message together with its execution-policy
// audit identity. Skill snapshots remain queryable even after deactivation.
func (s *Store) InsertMessageWithAudit(
	ctx context.Context,
	conversationID, sender, content string,
	usedTokens int,
	sourcesJSON string,
	partial bool,
	audit MessageAudit,
) (string, error) {
	var id string
	toolCallsJSON, err := encodeToolCalls(audit.ToolCalls)
	if err != nil {
		return "", err
	}
	err = s.pool.QueryRow(ctx,
		"INSERT INTO messages ("+
			" conversation_id, sender, content, used_tokens, sources_json, partial,"+
			" skill_id, skill_version, skill_policy_hash, model_used, model_provider, tool_calls_json)"+
			" VALUES ($1::uuid, $2, $3, $4, $5::jsonb, $6, $7::uuid, $8, $9, $10, $11, $12::jsonb)"+
			" RETURNING id::text",
		conversationID,
		sender,
		content,
		usedTokens,
		nilIfEmpty(sourcesJSON),
		partial,
		nilIfEmpty(audit.SkillID),
		nilIfZero(audit.SkillVersion),
		nilIfEmpty(audit.SkillPolicyHash),
		nilIfEmpty(audit.ModelUsed),
		nilIfEmpty(audit.ProviderUsed),
		nilIfEmpty(toolCallsJSON),
	).Scan(&id)
	return id, err
}

// InterruptedByDrain marks a BOT answer cut off by the shutdown drain; only
// such answers may be resumed (messages.interrupted_reason).
const InterruptedByDrain = "shutdown_drain"

// Resume errors (mapped to 404 / 400 by the HTTP layer).
var (
	ErrResumeNotFound      = errors.New("resume target not found")
	ErrResumeNotResumable  = errors.New("resume target is not the interrupted last turn")
	errResumeNoUserMessage = fmt.Errorf("%w: no preceding user message", ErrResumeNotResumable)
)

// ResumeTarget is an interrupted BOT turn claimed for regeneration.
type ResumeTarget struct {
	ConversationID string
	Question       string // the user turn the interrupted answer replied to
}

// CreateBotPlaceholder inserts an empty, partial BOT row at stream start so
// its id can be announced to the client before the answer exists.
func (s *Store) CreateBotPlaceholder(ctx context.Context, conversationID string) (string, error) {
	return s.InsertMessage(ctx, conversationID, "BOT", "", 0, "", true)
}

// DeleteBotPlaceholder removes a still-empty reserved BOT row (the turn failed
// before any answer was streamed).
func (s *Store) DeleteBotPlaceholder(ctx context.Context, messageID string) error {
	_, err := s.pool.Exec(ctx,
		"DELETE FROM messages WHERE id = $1::uuid AND sender = 'BOT' AND partial AND content = ''",
		messageID,
	)
	return err
}

// FinalizeBotMessage overwrites a BOT row (placeholder or resumed turn) with
// the produced answer. interruptedReason is "" or InterruptedByDrain.
func (s *Store) FinalizeBotMessage(
	ctx context.Context,
	messageID, content string,
	usedTokens int,
	sourcesJSON string,
	partial bool,
	interruptedReason string,
	audit MessageAudit,
) error {
	toolCallsJSON, err := encodeToolCalls(audit.ToolCalls)
	if err != nil {
		return err
	}
	_, err = s.pool.Exec(ctx,
		"UPDATE messages SET content = $2, used_tokens = $3, sources_json = $4::jsonb, partial = $5,"+
			" interrupted_reason = $6, skill_id = $7::uuid, skill_version = $8, skill_policy_hash = $9,"+
			" model_used = $10, model_provider = $11, tool_calls_json = $12::jsonb"+
			" WHERE id = $1::uuid AND sender = 'BOT'",
		messageID, content, usedTokens, nilIfEmpty(sourcesJSON), partial, nilIfEmpty(interruptedReason),
		nilIfEmpty(audit.SkillID), nilIfZero(audit.SkillVersion), nilIfEmpty(audit.SkillPolicyHash),
		nilIfEmpty(audit.ModelUsed), nilIfEmpty(audit.ProviderUsed), nilIfEmpty(toolCallsJSON),
	)
	return err
}

// ClaimInterruptedMessage atomically claims a drain-interrupted BOT turn for
// regeneration. The message must belong to workspaceID and to the caller (the
// user, or the widget session), be a BOT turn, be the newest message of its
// conversation and still carry the drain marker. Claiming clears the marker,
// so concurrent or repeated resumes of the same turn fail. Foreign, unknown or
// malformed ids yield ErrResumeNotFound.
func (s *Store) ClaimInterruptedMessage(
	ctx context.Context, messageID, workspaceID, userID, sessionKey string,
) (ResumeTarget, error) {
	var t ResumeTarget
	if !uuidPattern.MatchString(messageID) || !uuidPattern.MatchString(workspaceID) ||
		(userID == "" && sessionKey == "") {
		return t, ErrResumeNotFound
	}
	tx, err := s.pool.Begin(ctx)
	if err != nil {
		return t, err
	}
	defer func() { _ = tx.Rollback(ctx) }()

	var (
		reason    string
		createdAt time.Time
	)
	err = tx.QueryRow(ctx,
		"SELECT m.conversation_id::text, COALESCE(m.interrupted_reason, ''), m.created_at"+
			" FROM messages m JOIN conversations c ON c.id = m.conversation_id"+
			" WHERE m.id = $1::uuid AND m.sender = 'BOT' AND c.workspace_id = $2::uuid AND ("+
			"   ($3 <> '' AND c.user_id::text = $3)"+
			"   OR ($3 = '' AND $4 <> '' AND c.user_id IS NULL AND c.session_token = $4))"+
			" FOR UPDATE OF m",
		messageID, workspaceID, userID, sessionKey,
	).Scan(&t.ConversationID, &reason, &createdAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return ResumeTarget{}, ErrResumeNotFound
	}
	if err != nil {
		return ResumeTarget{}, err
	}
	var newer bool
	if err := tx.QueryRow(ctx,
		"SELECT EXISTS (SELECT 1 FROM messages WHERE conversation_id = $1::uuid AND id <> $2::uuid AND created_at >= $3)",
		t.ConversationID, messageID, createdAt,
	).Scan(&newer); err != nil {
		return ResumeTarget{}, err
	}
	if newer || reason != InterruptedByDrain {
		return ResumeTarget{}, ErrResumeNotResumable
	}
	err = tx.QueryRow(ctx,
		"SELECT content FROM messages WHERE conversation_id = $1::uuid AND sender = 'USER' AND created_at <= $2"+
			" ORDER BY created_at DESC LIMIT 1",
		t.ConversationID, createdAt,
	).Scan(&t.Question)
	if errors.Is(err, pgx.ErrNoRows) {
		return ResumeTarget{}, errResumeNoUserMessage
	}
	if err != nil {
		return ResumeTarget{}, err
	}
	if _, err := tx.Exec(ctx,
		"UPDATE messages SET interrupted_reason = NULL WHERE id = $1::uuid", messageID,
	); err != nil {
		return ResumeTarget{}, err
	}
	return t, tx.Commit(ctx)
}

// ReleaseInterruptedMessage restores the drain marker on a claimed turn whose
// regeneration failed before streaming began, so the client may retry.
func (s *Store) ReleaseInterruptedMessage(ctx context.Context, messageID string) error {
	_, err := s.pool.Exec(ctx,
		"UPDATE messages SET interrupted_reason = $2 WHERE id = $1::uuid AND interrupted_reason IS NULL AND partial",
		messageID, InterruptedByDrain,
	)
	return err
}

func encodeToolCalls(calls []ToolCallAudit) (string, error) {
	if len(calls) == 0 {
		return "", nil
	}
	b, err := json.Marshal(calls)
	if err != nil {
		return "", err
	}
	return string(b), nil
}

// RecentMessages returns the last `limit` completed turns of a conversation in
// chronological order (USER->user, BOT->assistant), powering server-side chat
// memory. Partial (aborted) turns are excluded.
func (s *Store) RecentMessages(ctx context.Context, conversationID string, limit int) ([]ports.Message, error) {
	rows, err := s.pool.Query(ctx,
		"SELECT sender, content FROM messages"+
			" WHERE conversation_id = $1::uuid AND sender IN ('USER','BOT') AND partial = false"+
			" ORDER BY created_at DESC LIMIT $2",
		conversationID, limit,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var reversed []ports.Message
	for rows.Next() {
		var sender, content string
		if err := rows.Scan(&sender, &content); err != nil {
			return nil, err
		}
		role := ports.RoleUser
		if sender == "BOT" {
			role = ports.RoleAssistant
		}
		reversed = append(reversed, ports.Message{Role: role, Content: content})
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	// Query was newest-first; flip to chronological.
	out := make([]ports.Message, len(reversed))
	for i, m := range reversed {
		out[len(reversed)-1-i] = m
	}
	return out, nil
}

// ── Admin oversight: read ANY conversation (SUPER_ADMIN / WORKSPACE_ADMIN) ────
// These intentionally drop the per-user filter that the self-service queries
// above enforce; the HTTP layer authorizes the caller and scopes by workspace.

// AdminConversationSummary is one row in the admin conversations browser.
type AdminConversationSummary struct {
	ID              string    `json:"id"`
	Title           string    `json:"title"`
	UserEmail       string    `json:"user_email"`
	UserID          string    `json:"user_id"`
	WorkspaceID     string    `json:"workspace_id"`
	WorkspaceName   string    `json:"workspace_name"`
	EvaluationScore float64   `json:"evaluation_score"`
	Flagged         bool      `json:"is_flagged"`
	CreatedAt       time.Time `json:"created_at"`
}

// AdminListConversations returns the most recent conversations across the given
// workspaces (newest first), titled by their first user message, with the owner
// email + workspace name + eval score/flag. Anonymous widget conversations have
// an empty user_email.
func (s *Store) AdminListConversations(ctx context.Context, workspaceIDs []string, limit int) ([]AdminConversationSummary, error) {
	rows, err := s.pool.Query(ctx,
		"SELECT c.id::text,"+
			" COALESCE((SELECT m.content FROM messages m"+
			"   WHERE m.conversation_id = c.id AND m.sender = 'USER'"+
			"   ORDER BY m.created_at ASC LIMIT 1), '') AS title,"+
			" COALESCE(u.email, ''), COALESCE(c.user_id::text, ''),"+
			" c.workspace_id::text, COALESCE(w.name, ''),"+
			" c.evaluation_score, c.is_flagged, c.created_at"+
			" FROM conversations c"+
			" LEFT JOIN users u ON u.id = c.user_id"+
			" LEFT JOIN workspaces w ON w.id = c.workspace_id"+
			" WHERE c.workspace_id = ANY($1::uuid[])"+
			"   AND EXISTS (SELECT 1 FROM messages m2"+
			"     WHERE m2.conversation_id = c.id AND m2.sender = 'USER')"+
			" ORDER BY c.created_at DESC LIMIT $2",
		workspaceIDs, limit,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []AdminConversationSummary
	for rows.Next() {
		var c AdminConversationSummary
		if err := rows.Scan(&c.ID, &c.Title, &c.UserEmail, &c.UserID,
			&c.WorkspaceID, &c.WorkspaceName, &c.EvaluationScore, &c.Flagged, &c.CreatedAt); err != nil {
			return nil, err
		}
		out = append(out, c)
	}
	return out, rows.Err()
}

// AdminConversationMessages returns a conversation's completed turns with no
// ownership predicate (the caller is an authorized admin scoped by workspace).
func (s *Store) AdminConversationMessages(ctx context.Context, conversationID string) ([]StoredMessage, error) {
	if !uuidPattern.MatchString(conversationID) {
		return nil, nil
	}
	rows, err := s.pool.Query(ctx,
		"SELECT m.sender, m.content, COALESCE(m.sources_json::text, '')"+
			" FROM messages m"+
			" WHERE m.conversation_id = $1::uuid"+
			"   AND m.partial = false AND m.sender IN ('USER','BOT')"+
			" ORDER BY m.created_at ASC",
		conversationID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []StoredMessage
	for rows.Next() {
		var sender, content, sources string
		if err := rows.Scan(&sender, &content, &sources); err != nil {
			return nil, err
		}
		role := ports.RoleUser
		if sender == "BOT" {
			role = ports.RoleAssistant
		}
		out = append(out, StoredMessage{Role: role, Content: content, Sources: sources})
	}
	return out, rows.Err()
}

// AdminConversationWorkspace returns a conversation's workspace id (for scoping
// the per-conversation authorization check). Empty string if not found.
func (s *Store) AdminConversationWorkspace(ctx context.Context, conversationID string) (string, error) {
	if !uuidPattern.MatchString(conversationID) {
		return "", pgx.ErrNoRows
	}
	var ws string
	err := s.pool.QueryRow(ctx,
		"SELECT workspace_id::text FROM conversations WHERE id = $1::uuid", conversationID,
	).Scan(&ws)
	return ws, err
}

// AdminPrincipal is the database view of an admin caller. The edge authorizes
// oversight from it rather than from token claims, so a demotion, org move or
// platform-admin revocation applies immediately.
type AdminPrincipal struct {
	Role          string
	OrgID         string // "" when the user has no org
	PlatformAdmin bool
}

// AdminPrincipalFor loads an ACTIVE user's role, org and platform-admin flag.
// A missing or deactivated user yields pgx.ErrNoRows.
func (s *Store) AdminPrincipalFor(ctx context.Context, userID string) (AdminPrincipal, error) {
	var p AdminPrincipal
	if !uuidPattern.MatchString(userID) {
		return p, pgx.ErrNoRows
	}
	err := s.pool.QueryRow(ctx,
		"SELECT role, COALESCE(org_id::text, ''), is_platform_admin FROM users"+
			" WHERE id = $1::uuid AND is_active = TRUE",
		userID,
	).Scan(&p.Role, &p.OrgID, &p.PlatformAdmin)
	return p, err
}

// AllWorkspaceIDs returns every workspace (the default oversight listing of a
// platform admin that belongs to no org).
func (s *Store) AllWorkspaceIDs(ctx context.Context) ([]string, error) {
	rows, err := s.pool.Query(ctx, "SELECT id::text FROM workspaces")
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	return scanIDs(rows)
}

// AdminWorkspaceIDsForUser returns the workspaces a WORKSPACE_ADMIN may oversee:
// their effective set (direct membership or inherited via the team closure).
func (s *Store) AdminWorkspaceIDsForUser(ctx context.Context, userID string) ([]string, error) {
	rows, err := s.pool.Query(ctx,
		"SELECT w.id::text FROM workspaces w WHERE"+
			"  w.id IN (SELECT workspace_id FROM workspace_members WHERE user_id = $1::uuid)"+
			"  OR w.team_id IN ("+
			"     SELECT tc.descendant_id FROM team_closure tc"+
			"     JOIN team_members tm ON tm.team_id = tc.ancestor_id"+
			"     WHERE tm.user_id = $1::uuid)",
		userID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	return scanIDs(rows)
}

// AdminOrgWorkspaceIDs returns every workspace in an organization (the scope a
// SUPER_ADMIN oversees). An empty orgID yields no workspaces: SUPER_ADMIN is
// org-scoped, and a token without an org must never widen to every org.
func (s *Store) AdminOrgWorkspaceIDs(ctx context.Context, orgID string) ([]string, error) {
	if orgID == "" {
		return nil, nil
	}
	rows, err := s.pool.Query(ctx, "SELECT id::text FROM workspaces WHERE org_id = $1::uuid", orgID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	return scanIDs(rows)
}

// pgxRows is the minimal row-iterator surface used by scanIDs (pgx.Rows).
type pgxRows interface {
	Next() bool
	Scan(dest ...any) error
	Err() error
	Close()
}

func scanIDs(rows pgxRows) ([]string, error) {
	var ids []string
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			return nil, err
		}
		ids = append(ids, id)
	}
	return ids, rows.Err()
}

// HasConnectedJira reports whether the workspace's organization has a CONNECTED
// `jira` integration (the coarse Phase-1 gate for MCP Jira tools). The org is
// derived from the workspace so this works for both INTERNAL (admin token) and
// EXTERNAL (widget) chats, which only carry a workspace id. Fail-soft: callers
// treat any error as "no Jira" and proceed without tools.
//
// Contract (shared with the control-plane integrations catalog): provider key is
// 'jira' and status is 'connected' when active. The edge never reads the
// credentials — the mcp-atlassian container holds them via env, i.e. they are
// the OPERATOR's credentials. So a row only counts when a platform admin
// created it: org-created rows (or legacy rows with no creator) marked
// connected, possibly with dummy credentials, never unlock the operator's Jira.
func (s *Store) HasConnectedJira(ctx context.Context, workspaceID string) (bool, error) {
	var ok bool
	err := s.pool.QueryRow(ctx,
		"SELECT EXISTS ("+
			" SELECT 1 FROM integrations i"+
			" JOIN workspaces w ON w.org_id = i.org_id"+
			" JOIN users u ON u.id = i.created_by AND u.is_platform_admin"+
			" WHERE w.id = $1::uuid AND i.provider = 'jira' AND i.status = 'connected'"+
			")",
		workspaceID,
	).Scan(&ok)
	return ok, err
}

// GetUserMemory returns a user's durable memory facts (newest first).
func (s *Store) GetUserMemory(ctx context.Context, userID string, limit int) ([]string, error) {
	rows, err := s.pool.Query(ctx,
		"SELECT content FROM user_memory WHERE user_id = $1::uuid"+
			" ORDER BY created_at DESC LIMIT $2",
		userID, limit,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []string
	for rows.Next() {
		var c string
		if err := rows.Scan(&c); err != nil {
			return nil, err
		}
		out = append(out, c)
	}
	return out, rows.Err()
}

// AddUserMemory upserts deduped facts for a user (identical content is ignored).
func (s *Store) AddUserMemory(ctx context.Context, userID string, facts []string) error {
	for _, f := range facts {
		if _, err := s.pool.Exec(ctx,
			"INSERT INTO user_memory (user_id, content) VALUES ($1::uuid, $2)"+
				" ON CONFLICT (user_id, content) DO NOTHING",
			userID, f,
		); err != nil {
			return err
		}
	}
	return nil
}

// InsertMessageFeedback records a 👍/👎 on a BOT message by the conversation's
// owner. Ownership is enforced in SQL (the message must belong to a conversation
// owned by userID); a non-owner gets ok=false (no error). A 'down' rating also
// flags the conversation so it surfaces in the flagged-review queue. Re-voting
// overwrites the prior vote.
func (s *Store) InsertMessageFeedback(ctx context.Context, messageID, userID, rating string) (bool, error) {
	if !uuidPattern.MatchString(messageID) {
		return false, nil // unknown message
	}
	var convID string
	err := s.pool.QueryRow(ctx,
		"SELECT c.id::text FROM messages m JOIN conversations c ON c.id = m.conversation_id"+
			" WHERE m.id = $1::uuid AND c.user_id = $2::uuid",
		messageID, userID,
	).Scan(&convID)
	if errors.Is(err, pgx.ErrNoRows) {
		return false, nil // not the owner, or unknown message
	}
	if err != nil {
		return false, err
	}
	if _, err := s.pool.Exec(ctx,
		"INSERT INTO message_feedback (message_id, user_id, rating)"+
			" VALUES ($1::uuid, $2::uuid, $3)"+
			" ON CONFLICT (message_id, user_id) DO UPDATE SET rating = EXCLUDED.rating, created_at = now()",
		messageID, userID, rating,
	); err != nil {
		return false, err
	}
	if rating == "down" {
		// Best-effort: surface a thumbs-down for review.
		_, _ = s.pool.Exec(ctx,
			"UPDATE conversations SET is_flagged = true WHERE id = $1::uuid", convID)
	}
	return true, nil
}

func nilIfEmpty(s string) any {
	if s == "" {
		return nil
	}
	return s
}

func nilIfZero(n int) any {
	if n == 0 {
		return nil
	}
	return n
}
