// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"

	"github.com/alicangunduz/raggie/services/edge/internal/bus"
	"github.com/alicangunduz/raggie/services/edge/internal/store"
)

// botTurn is the assistant message of one chat turn. Its id is reserved at
// stream start (a placeholder row, or the interrupted turn being resumed) so
// the client learns it from the first `meta` event and can resume it after a
// drain-forced `reconnect`.
type botTurn struct {
	conversationID string
	messageID      string // "" when persistence is unavailable
}

// writeMetaEvent announces the conversation and the reserved assistant message.
func writeMetaEvent(w http.ResponseWriter, t botTurn) {
	if t.conversationID == "" {
		return
	}
	meta := map[string]string{"conversation_id": t.conversationID}
	if t.messageID != "" {
		meta["message_id"] = t.messageID
	}
	data, _ := json.Marshal(meta)
	fmt.Fprintf(w, "event: meta\ndata: %s\n\n", data)
}

// persistBotTurn writes the produced answer into the reserved row (or inserts
// one when no row could be reserved) and publishes chat.completed on full
// completion. A drain-cancelled turn is stored partial + InterruptedByDrain so
// it can be resumed. Uses a fresh context: a client disconnect mid-flush must
// not lose what was already produced. Returns the message id ("" on failure).
func persistBotTurn(
	ctx context.Context, deps Deps, logger *slog.Logger, t botTurn, workspaceID string,
	answer string, usedTokens int, sourcesJSON string, completed bool, audit store.MessageAudit,
) string {
	if deps.Store == nil || t.conversationID == "" {
		return ""
	}
	bg := context.Background()
	interrupted := ""
	if !completed && drainCancelled(ctx) {
		interrupted = store.InterruptedByDrain
	}
	msgID := t.messageID
	var err error
	if msgID != "" {
		err = deps.Store.FinalizeBotMessage(bg, msgID, answer, usedTokens, sourcesJSON, !completed, interrupted, audit)
	} else {
		msgID, err = deps.Store.InsertMessageWithAudit(bg, t.conversationID, "BOT", answer, usedTokens, sourcesJSON, !completed, audit)
	}
	if err != nil {
		logger.Error("persist bot message", "err", err)
		return ""
	}
	if completed && deps.Bus != nil {
		if pe := deps.Bus.Publish(bg, bus.ChatCompleted, map[string]any{
			"message_id":      msgID,
			"conversation_id": t.conversationID,
			"workspace_id":    workspaceID,
		}); pe != nil {
			logger.Error("publish chat.completed", "err", pe)
		}
	}
	return msgID
}
