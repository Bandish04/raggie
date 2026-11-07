// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/alicangunduz/raggie/services/edge/internal/ports"
	"github.com/alicangunduz/raggie/services/edge/internal/ports/mock"
	"github.com/alicangunduz/raggie/services/edge/internal/store"
	"github.com/alicangunduz/raggie/services/edge/internal/widgetauth"
)

func webChatRequest(t *testing.T, widget, deep bool) *http.Request {
	t.Helper()
	body, err := json.Marshal(map[string]any{
		"workspace_id": "ws1",
		"message":      "What changed in the EU AI Act this week?",
		"web_search":   !deep,
		"deep_search":  deep,
	})
	if err != nil {
		t.Fatal(err)
	}
	req := httptest.NewRequest(http.MethodPost, "/api/v1/chat/stream", strings.NewReader(string(body)))
	if widget {
		tok, err := widgetauth.Mint("test-secret", "ws1", 30*time.Minute, time.Now())
		if err != nil {
			t.Fatal(err)
		}
		req.Header.Set("Origin", "https://acme.example")
		req.Header.Set("Authorization", "Bearer "+tok)
	} else {
		req.Header.Set("Authorization", "Bearer "+adminToken(t, "SUPER_ADMIN", "user-1"))
	}
	return req
}

// Web and deep research make paid outbound calls. The anonymous widget gets
// them only when BOTH the widget kill switch (WIDGET_WEB_SEARCH_ENABLED) and
// the workspace web_search toggle are on; internal chats need only the
// workspace toggle (on top of WEB_SEARCH_ENABLED). Both loops, both modes.
func TestWidgetWebSearchIsDoubleGated(t *testing.T) {
	cases := []struct {
		name      string
		widget    bool
		widgetEnv bool
		wsToggle  bool
		wantWeb   bool
	}{
		{"widget env off, workspace off", true, false, false, false},
		{"widget env on, workspace off", true, true, false, false},
		{"widget env off, workspace on", true, false, true, false},
		{"widget env on, workspace on", true, true, true, true},
		{"internal, workspace on", false, false, true, true},
		{"internal, workspace off", false, true, false, false},
	}
	for _, unified := range []bool{false, true} {
		for _, deep := range []bool{false, true} {
			for _, tc := range cases {
				name := map[bool]string{false: "legacy", true: "unified"}[unified] + "-" +
					map[bool]string{false: "web", true: "deep"}[deep] + "-" + tc.name
				t.Run(name, func(t *testing.T) {
					web := &mock.WebSearcher{Default: []ports.WebResult{{Title: "News", URL: "https://example.com/n", Snippet: "news"}}}
					deps := memoryDeps(&fakeMemory{}, &memoryChat{}, memoryCase{widget: tc.widget})
					deps.Memory = nil
					deps.Web = web
					deps.Features = fakeFeatures{flags: store.WorkspaceFeatureFlags{WebSearch: tc.wsToggle}}
					cfg := widgetCfg()
					cfg.WebSearchEnabled, cfg.WebSearchTopN, cfg.DeepSearchMaxQueries, cfg.DeepSearchTopN, cfg.DeepSearchMaxResults = true, 3, 2, 3, 10
					cfg.WidgetWebSearchEnabled = tc.widgetEnv
					cfg.AgentUnifiedLoop, cfg.AgentMaxIterations = unified, 4
					srv := New(cfg, discardLogger(), deps)

					rec := httptest.NewRecorder()
					srv.Handler.ServeHTTP(rec, webChatRequest(t, tc.widget, deep))
					if rec.Code != http.StatusOK || !strings.Contains(rec.Body.String(), "[DONE]") {
						t.Fatalf("chat: %d %s", rec.Code, rec.Body.String())
					}
					if got := len(web.AskedQueries()) > 0; got != tc.wantWeb {
						t.Fatalf("outbound web searches made = %v (%d), want %v", got, len(web.AskedQueries()), tc.wantWeb)
					}
				})
			}
		}
	}
}
