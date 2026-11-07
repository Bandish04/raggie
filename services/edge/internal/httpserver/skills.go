// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"strings"
	"time"

	"github.com/alicangunduz/raggie/services/edge/internal/config"
	"github.com/alicangunduz/raggie/services/edge/internal/llm"
	"github.com/alicangunduz/raggie/services/edge/internal/locale"
	"github.com/alicangunduz/raggie/services/edge/internal/ports"
)

// maxSkillDescriptionLen bounds the user-supplied skill description (runes) so a
// pathological body cannot blow up the meta-prompt / token cost.
const maxSkillDescriptionLen = 2000

type generateInstructionsRequest struct {
	Description string `json:"description"`
}

type generateInstructionsResponse struct {
	Instructions string `json:"instructions"`
}

// generateInstructionsHandler: POST /api/v1/skills/generate-instructions —
// authenticated INTERNAL users only (aud=admin access token). Turns a short user
// description into a skill system prompt (in the description's language) via ONE non-streamed completion
// on the chat pool (same one-shot pattern as generateSubQueries). The completion
// is drained fully so the pool slot is released.
func generateInstructionsHandler(cfg config.Config, deps Deps, logger *slog.Logger) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if _, ok := adminUserID(cfg, deps, w, r); !ok {
			return
		}

		var req generateInstructionsRequest
		if err := decodeJSONBody(w, r, 1<<16, &req); errors.Is(err, errBodyTooLarge) {
			writeError(w, r, http.StatusRequestEntityTooLarge, errCodeTooLarge)
			return
		} else if err != nil {
			writeError(w, r, http.StatusBadRequest, errCodeBadRequest)
			return
		}
		desc := strings.TrimSpace(req.Description)
		if desc == "" || len([]rune(desc)) > maxSkillDescriptionLen {
			writeError(w, r, http.StatusBadRequest, errCodeBadRequest)
			return
		}

		genCtx, cancel := context.WithTimeout(r.Context(), 30*time.Second)
		defer cancel()
		msgs := []ports.Message{
			{Role: ports.RoleSystem, Content: locale.Pick(skillInstructionsPrompt, requestLocale(r.Context()))},
			{Role: ports.RoleUser, Content: desc},
		}
		// Model empty → provider falls back to the configured default chat model.
		stream, err := deps.Chat.Stream(genCtx, ports.ChatRequest{Messages: msgs, Temperature: 0.4, MaxTokens: 700})
		if err != nil {
			if errors.Is(err, llm.ErrUpstreamBusy) {
				writeError(w, r, http.StatusServiceUnavailable, errCodeBusy)
				return
			}
			logger.Error("skill instructions generation failed", "err", err)
			writeError(w, r, http.StatusBadGateway, errCodeUpstream)
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
			// Only collect answer content; ignore any reasoning deltas.
			b.WriteString(chunk.Delta)
		}
		instructions := strings.TrimSpace(b.String())
		if streamErr != nil || !completed || instructions == "" {
			logger.Error("skill instructions generation produced incomplete output", "err", streamErr)
			writeError(w, r, http.StatusBadGateway, errCodeUpstream)
			return
		}
		writeJSON(w, http.StatusOK, generateInstructionsResponse{Instructions: instructions})
	}
}
