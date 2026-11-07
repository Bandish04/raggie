// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"strings"

	"github.com/alicangunduz/raggie/services/edge/internal/ports"
)

// clientHistoryMaxChars caps one client-supplied history turn (in runes). It is
// generous for a real earlier answer and keeps a forged turn from crowding the
// retrieved context out of the prompt.
const clientHistoryMaxChars = 8000

// sanitizeClientHistory reduces client-sent history to plain conversation: only
// user/assistant turns with text, no tool-call fields, each capped at
// clientHistoryMaxChars, and only the newest maxTurns (HISTORY_MAX_MESSAGES;
// <= 0 disables history). System, tool and any other role is dropped: the
// system prompt is server-assembled and tool turns only come from this
// server's own tool loop.
func sanitizeClientHistory(history []ports.Message, maxTurns int) []ports.Message {
	if maxTurns <= 0 {
		return nil
	}
	out := make([]ports.Message, 0, min(len(history), maxTurns))
	for _, m := range history {
		if m.Role != ports.RoleUser && m.Role != ports.RoleAssistant {
			continue
		}
		content := m.Content
		if strings.TrimSpace(content) == "" {
			continue
		}
		if r := []rune(content); len(r) > clientHistoryMaxChars {
			content = string(r[:clientHistoryMaxChars])
		}
		out = append(out, ports.Message{Role: m.Role, Content: content})
	}
	if len(out) > maxTurns {
		out = out[len(out)-maxTurns:]
	}
	return out
}
