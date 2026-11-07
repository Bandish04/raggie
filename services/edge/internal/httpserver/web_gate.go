// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"github.com/alicangunduz/raggie/services/edge/internal/config"
	"github.com/alicangunduz/raggie/services/edge/internal/store"
)

// webSearchGated reports whether web/deep research may run this turn: the
// global WEB_SEARCH_ENABLED switch, a configured searcher and the workspace
// web_search toggle. Searches are paid outbound calls, so an anonymous widget
// session additionally needs the WIDGET_WEB_SEARCH_ENABLED kill switch.
func webSearchGated(cfg config.Config, deps Deps, feats store.WorkspaceFeatureFlags, widgetSession bool) bool {
	if widgetSession && !cfg.WidgetWebSearchEnabled {
		return false
	}
	return cfg.WebSearchEnabled && deps.Web != nil && feats.WebSearch
}
