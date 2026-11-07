// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"context"
	"log/slog"
	"net/http"
	"time"

	"github.com/alicangunduz/raggie/services/edge/internal/config"
)

func readinessHandler(cfg config.Config, checks []ReadinessCheck, drain *Drainer, logger *slog.Logger) http.HandlerFunc {
	timeout := time.Duration(cfg.ReadinessTimeoutSeconds) * time.Second
	if timeout <= 0 {
		timeout = 3 * time.Second
	}
	return func(w http.ResponseWriter, r *http.Request) {
		// A draining replica leaves rotation at once, before probing anything.
		if drain != nil && drain.NotReady() {
			writeJSON(w, http.StatusServiceUnavailable, map[string]string{"status": "draining", "service": "edge"})
			return
		}
		ctx, cancel := context.WithTimeout(r.Context(), timeout)
		defer cancel()

		statuses := make(map[string]string, len(checks))
		failed := make([]string, 0)
		degraded := make([]string, 0)
		for _, check := range checks {
			if check.Name == "" || check.Probe == nil {
				continue
			}
			if err := check.Probe.Ready(ctx); err != nil {
				statuses[check.Name] = "unavailable"
				if check.Required {
					failed = append(failed, check.Name)
				} else {
					degraded = append(degraded, check.Name)
				}
				logger.Warn("readiness dependency failed", "dependency", check.Name, "err", err)
				continue
			}
			statuses[check.Name] = "ok"
		}

		if len(failed) > 0 {
			writeJSON(w, http.StatusServiceUnavailable, map[string]any{
				"status": "not_ready",
				"checks": statuses,
				"failed": failed,
			})
			return
		}
		if len(degraded) > 0 {
			writeJSON(w, http.StatusOK, map[string]any{
				"status":   "degraded",
				"checks":   statuses,
				"degraded": degraded,
			})
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{
			"status": "ready",
			"checks": statuses,
		})
	}
}
