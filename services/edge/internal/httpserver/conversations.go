// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"errors"
	"log/slog"
	"net/http"
	"strconv"
	"time"

	"github.com/alicangunduz/raggie/services/edge/internal/config"
	"github.com/alicangunduz/raggie/services/edge/internal/store"
	"github.com/alicangunduz/raggie/services/edge/internal/widgetauth"
)

func verifiedAdminClaims(cfg config.Config, deps Deps, r *http.Request) (map[string]any, bool) {
	claims, err := widgetauth.ParseHS256(cfg.JWTSecret, bearer(r), time.Now())
	if err != nil || claims["aud"] != "admin" || claims["type"] != "access" {
		return nil, false
	}
	sub, _ := claims["sub"].(string)
	if sub == "" {
		return nil, false
	}
	if deps.TokenState != nil {
		sessionID, _ := claims["sid"].(string)
		if sessionID == "" {
			return nil, false
		}
		active, err := deps.TokenState.UserSessionActive(r.Context(), sub, sessionID)
		if err != nil || !active {
			return nil, false
		}
	}
	return claims, true
}

// adminUserID verifies an aud=admin access token and returns the user id (sub).
// On failure it writes 401 and returns ok=false.
func adminUserID(cfg config.Config, deps Deps, w http.ResponseWriter, r *http.Request) (string, bool) {
	claims, ok := verifiedAdminClaims(cfg, deps, r)
	if !ok {
		writeError(w, r, http.StatusUnauthorized, errCodeUnauth)
		return "", false
	}
	sub, _ := claims["sub"].(string)
	return sub, true
}

// listConversationsHandler: GET /api/v1/conversations — the authenticated user's
// recent conversations (newest first), for the chat history sidebar.
func listConversationsHandler(cfg config.Config, deps Deps, logger *slog.Logger) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if deps.Store == nil {
			writeJSON(w, http.StatusOK, []store.ConversationSummary{})
			return
		}
		userID, ok := adminUserID(cfg, deps, w, r)
		if !ok {
			return
		}
		limit := 30
		if v := r.URL.Query().Get("limit"); v != "" {
			if n, e := strconv.Atoi(v); e == nil && n > 0 && n <= 100 {
				limit = n
			}
		}
		convs, err := deps.Store.ListConversations(r.Context(), userID, limit)
		if err != nil {
			logger.Error("list conversations", "err", err)
			writeError(w, r, http.StatusBadGateway, errCodeInternal)
			return
		}
		if convs == nil {
			convs = []store.ConversationSummary{}
		}
		writeJSON(w, http.StatusOK, convs)
	}
}

// conversationMessagesHandler: GET /api/v1/conversations/{id}/messages — the
// turns of one of the user's conversations (ownership enforced in the query).
func conversationMessagesHandler(cfg config.Config, deps Deps, logger *slog.Logger) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if deps.Store == nil {
			writeJSON(w, http.StatusOK, []store.StoredMessage{})
			return
		}
		userID, ok := adminUserID(cfg, deps, w, r)
		if !ok {
			return
		}
		convID := r.PathValue("id")
		if convID == "" {
			writeError(w, r, http.StatusBadRequest, errCodeBadRequest)
			return
		}
		// Non-owners (and unknown or malformed ids) get 404, never an empty
		// 200, so the route's contract matches delete/feedback.
		owned, err := deps.Store.UserOwnsConversation(r.Context(), convID, userID)
		if err != nil {
			logger.Error("conversation ownership", "err", err)
			writeError(w, r, http.StatusBadGateway, errCodeInternal)
			return
		}
		if !owned {
			writeError(w, r, http.StatusNotFound, errCodeNotFound)
			return
		}
		msgs, err := deps.Store.ConversationMessages(r.Context(), convID, userID)
		if err != nil {
			logger.Error("conversation messages", "err", err)
			writeError(w, r, http.StatusBadGateway, errCodeInternal)
			return
		}
		if msgs == nil {
			msgs = []store.StoredMessage{}
		}
		writeJSON(w, http.StatusOK, msgs)
	}
}

// deleteConversationHandler: DELETE /api/v1/conversations/{id} — delete one of
// the caller's own conversations and its messages (clear a single chat).
// Ownership is enforced in the store (user_id predicate); a 404 covers both an
// unknown id and a conversation owned by someone else / anonymous.
func deleteConversationHandler(cfg config.Config, deps Deps, logger *slog.Logger) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if deps.Store == nil {
			writeError(w, r, http.StatusServiceUnavailable, errCodeUnavailable)
			return
		}
		userID, ok := adminUserID(cfg, deps, w, r)
		if !ok {
			return
		}
		convID := r.PathValue("id")
		if convID == "" {
			writeError(w, r, http.StatusBadRequest, errCodeBadRequest)
			return
		}
		deleted, err := deps.Store.DeleteConversation(r.Context(), convID, userID)
		if err != nil {
			logger.Error("delete conversation", "err", err)
			writeError(w, r, http.StatusBadGateway, errCodeInternal)
			return
		}
		if !deleted {
			writeError(w, r, http.StatusNotFound, errCodeNotFound)
			return
		}
		w.WriteHeader(http.StatusNoContent)
	}
}

// deleteAllConversationsHandler: DELETE /api/v1/conversations — delete ALL of
// the caller's conversations and their messages (clear history). Anonymous
// widget conversations are never touched. Responds 200 {"deleted": n}.
func deleteAllConversationsHandler(cfg config.Config, deps Deps, logger *slog.Logger) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if deps.Store == nil {
			writeJSON(w, http.StatusOK, map[string]int{"deleted": 0})
			return
		}
		userID, ok := adminUserID(cfg, deps, w, r)
		if !ok {
			return
		}
		n, err := deps.Store.DeleteAllConversations(r.Context(), userID)
		if err != nil {
			logger.Error("delete all conversations", "err", err)
			writeError(w, r, http.StatusBadGateway, errCodeInternal)
			return
		}
		writeJSON(w, http.StatusOK, map[string]int{"deleted": n})
	}
}

// messageFeedbackHandler: POST /api/v1/messages/{id}/feedback — record a 👍/👎
// on a BOT answer. Only the conversation owner may rate (enforced in the store).
func messageFeedbackHandler(cfg config.Config, deps Deps, logger *slog.Logger) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if deps.Store == nil {
			writeError(w, r, http.StatusServiceUnavailable, errCodeUnavailable)
			return
		}
		userID, ok := adminUserID(cfg, deps, w, r)
		if !ok {
			return
		}
		msgID := r.PathValue("id")
		if msgID == "" {
			writeError(w, r, http.StatusBadRequest, errCodeBadRequest)
			return
		}
		var body struct {
			Rating string `json:"rating"`
		}
		if err := decodeJSONBody(w, r, smallJSONBodyBytes, &body); errors.Is(err, errBodyTooLarge) {
			writeError(w, r, http.StatusRequestEntityTooLarge, errCodeTooLarge)
			return
		} else if err != nil || (body.Rating != "up" && body.Rating != "down") {
			writeError(w, r, http.StatusBadRequest, errCodeBadRequest)
			return
		}
		okFb, err := deps.Store.InsertMessageFeedback(r.Context(), msgID, userID, body.Rating)
		if err != nil {
			logger.Error("message feedback", "err", err)
			writeError(w, r, http.StatusBadGateway, errCodeInternal)
			return
		}
		if !okFb {
			writeError(w, r, http.StatusNotFound, errCodeNotFound)
			return
		}
		w.WriteHeader(http.StatusNoContent)
	}
}
