// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"log/slog"
	"net/http"
	"sync"
	"time"

	"github.com/alicangunduz/raggie/services/edge/internal/config"
	"github.com/alicangunduz/raggie/services/edge/internal/ports"
)

// modelsCacheTTL bounds how often we hit the provider's /models. The list changes
// rarely and this is an admin discovery call, so a short cache is plenty.
const modelsCacheTTL = 5 * time.Minute

// modelsCache memoises the last successful provider model list. Guarded by a
// mutex; a single global cache is fine since the list is provider-wide (not
// per-user / per-workspace).
type modelsCache struct {
	mu       sync.Mutex
	ids      []string
	profiles []ports.ModelDescriptor
	fetched  time.Time
}

var modelsCacheState modelsCache

type modelsResponse struct {
	Models   []string                `json:"models"`
	Profiles []ports.ModelDescriptor `json:"profiles,omitempty"`
}

// modelsHandler serves GET /api/v1/models: the chat models the provider exposes,
// for an admin to pick from. Shape: {"models":["id1","id2",...]}. Requires an
// aud=admin access token. Degrades gracefully — a provider error returns an empty
// list with 200 so the admin UI can fall back to the configured default model.
func modelsHandler(cfg config.Config, deps Deps, logger *slog.Logger) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if _, ok := adminUserID(cfg, deps, w, r); !ok {
			return
		}
		if deps.Models == nil {
			writeJSON(w, http.StatusOK, modelsResponse{Models: []string{}})
			return
		}

		// Serve from cache when warm.
		modelsCacheState.mu.Lock()
		if time.Since(modelsCacheState.fetched) < modelsCacheTTL && modelsCacheState.ids != nil {
			ids := append([]string(nil), modelsCacheState.ids...)
			profiles := append([]ports.ModelDescriptor(nil), modelsCacheState.profiles...)
			modelsCacheState.mu.Unlock()
			writeJSON(w, http.StatusOK, modelsResponse{Models: ids, Profiles: profiles})
			return
		}
		modelsCacheState.mu.Unlock()

		var (
			ids      []string
			profiles []ports.ModelDescriptor
			err      error
		)
		if lister, ok := deps.Models.(ports.ModelProfileLister); ok {
			profiles, err = lister.ListModelProfiles(r.Context())
			for _, profile := range profiles {
				if profile.Available {
					ids = append(ids, profile.ID)
				}
			}
		} else {
			ids, err = deps.Models.ListModels(r.Context())
		}
		if err != nil {
			logger.Warn("provider model list failed; returning empty list",
				"err", err, "request_id", requestIDOf(r.Context()))
			writeJSON(w, http.StatusOK, modelsResponse{Models: []string{}})
			return
		}
		if ids == nil {
			ids = []string{}
		}

		modelsCacheState.mu.Lock()
		modelsCacheState.ids = append([]string(nil), ids...)
		modelsCacheState.profiles = append([]ports.ModelDescriptor(nil), profiles...)
		modelsCacheState.fetched = time.Now()
		modelsCacheState.mu.Unlock()

		writeJSON(w, http.StatusOK, modelsResponse{Models: ids, Profiles: profiles})
	}
}
