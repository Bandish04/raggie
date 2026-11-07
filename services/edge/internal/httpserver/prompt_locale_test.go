// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/alicangunduz/raggie/services/edge/internal/config"
	"github.com/alicangunduz/raggie/services/edge/internal/locale"
	"github.com/alicangunduz/raggie/services/edge/internal/ports"
	"github.com/alicangunduz/raggie/services/edge/internal/ports/mock"
	"github.com/alicangunduz/raggie/services/edge/internal/rag"
)

const (
	enMarker = "ALWAYS answer in the language of the user's question"
	trMarker = "HER ZAMAN kullanıcının sorusunun dilinde cevap ver"
)

func promptFor(t *testing.T, cfg config.Config, body, acceptLang string) string {
	t.Helper()
	chat := &recordingChat{}
	vs := mock.VectorStore{Chunks: []ports.Chunk{{DocumentID: "d", Filename: "a.pdf", Text: "x", Score: 0.9}}}
	srv := New(cfg, discardLogger(), hotPath(Deps{RAG: rag.New(mock.QueryEmbedder{Dim: 8}, vs), Chat: chat}))
	req := httptest.NewRequest(http.MethodPost, "/api/v1/chat/stream", strings.NewReader(body))
	if acceptLang != "" {
		req.Header.Set("Accept-Language", acceptLang)
	}
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("chat: %d %s", rec.Code, rec.Body.String())
	}
	return chat.prompts()
}

func TestChatPromptLocaleSelection(t *testing.T) {
	trDefault := testCfg()
	trDefault.DefaultLocale = locale.TR
	cases := []struct {
		name, body, acceptLang string
		cfg                    config.Config
		want                   string
	}{
		{"english by default", `{"workspace_id":"ws1","message":"hi"}`, "", testCfg(), enMarker},
		{"DEFAULT_LOCALE=tr", `{"workspace_id":"ws1","message":"hi"}`, "", trDefault, trMarker},
		{"widget browser asks for Turkish", `{"workspace_id":"ws1","message":"merhaba"}`, "tr-TR,tr;q=0.9", testCfg(), trMarker},
		{"explicit locale field beats Accept-Language", `{"workspace_id":"ws1","message":"hi","locale":"en"}`, "tr", trDefault, enMarker},
		{"explicit tr field", `{"workspace_id":"ws1","message":"hi","locale":"tr-TR"}`, "", testCfg(), trMarker},
		{"unsupported locale falls through", `{"workspace_id":"ws1","message":"hi","locale":"de"}`, "de-DE", testCfg(), enMarker},
	}
	for _, tc := range cases {
		for _, unified := range []bool{false, true} {
			cfg := tc.cfg
			cfg.AgentUnifiedLoop = unified
			got := promptFor(t, cfg, tc.body, tc.acceptLang)
			if !strings.Contains(got, tc.want) {
				t.Errorf("%s (unified=%v): expected %q template, prompt was:\n%s", tc.name, unified, tc.want, got)
			}
		}
	}
}

// A non-vision model drops attachments with a note in the request locale.
func TestVisionDropNoteIsLocalized(t *testing.T) {
	body := `{"workspace_id":"ws1","message":"look","attachments":[{"type":"image","data_url":"data:image/png;base64,AAAA"}]}`
	if got := promptFor(t, testCfg(), body, ""); !strings.Contains(got, locale.Pick(visionDropNote, locale.EN)) {
		t.Fatalf("expected the English vision note:\n%s", got)
	}
	if got := promptFor(t, testCfg(), body, "tr"); !strings.Contains(got, locale.Pick(visionDropNote, locale.TR)) {
		t.Fatalf("expected the Turkish vision note:\n%s", got)
	}
}

// Helper prompts (skill generation, schedule parse) follow the request locale.
func TestHelperPromptsFollowLocale(t *testing.T) {
	for _, tc := range []struct {
		acceptLang, skillWant, schedWant string
	}{
		{"", "Write in the same language as the user's description.", "Current time:"},
		{"tr", "Kullanıcının açıklamasıyla aynı dilde yaz.", "Şu anki zaman:"},
	} {
		chat := &recordingChat{}
		deps := hotPath(Deps{Chat: chat, RAG: rag.New(mock.QueryEmbedder{Dim: 8}, mock.VectorStore{})})
		srv := New(widgetCfg(), discardLogger(), deps)
		for _, path := range []string{"/api/v1/skills/generate-instructions", "/api/v1/schedule/parse"} {
			body := `{"description":"hr helper"}`
			if strings.Contains(path, "schedule") {
				body = `{"text":"every morning"}`
			}
			req := httptest.NewRequest(http.MethodPost, path, strings.NewReader(body))
			req.Header.Set("Authorization", "Bearer "+adminToken(t, "STAFF", "u1"))
			if tc.acceptLang != "" {
				req.Header.Set("Accept-Language", tc.acceptLang)
			}
			srv.Handler.ServeHTTP(httptest.NewRecorder(), req)
		}
		got := chat.prompts()
		if !strings.Contains(got, tc.skillWant) || !strings.Contains(got, tc.schedWant) {
			t.Fatalf("Accept-Language=%q: helper prompts not localized:\n%s", tc.acceptLang, got)
		}
	}
}

// The search-plan prompt uses the configured default country, not a
// hard-coded one.
func TestSearchPlanUsesConfiguredCountry(t *testing.T) {
	got := searchPlanFor(locale.EN, "de")
	if !strings.Contains(got, `"country":"DE"`) || strings.Contains(got, "{COUNTRY}") {
		t.Fatalf("country not substituted: %s", got)
	}
}

// Every localized helper map has both locales.
func TestHelperPromptCatalogIsComplete(t *testing.T) {
	maps := map[string]map[locale.Locale]string{
		"memoryExtractionPrompt": memoryExtractionPrompt, "memoryBlockHeader": memoryBlockHeader,
		"subQueryPrompt": subQueryPrompt, "webQueryPrompt": webQueryPrompt, "searchPlanPrompt": searchPlanPrompt,
		"followupQueryPrompt": followupQueryPrompt, "scheduleParsePrompt": scheduleParsePrompt,
		"skillInstructionsPrompt": skillInstructionsPrompt, "visionDropNote": visionDropNote,
		"iterLimitNote": iterLimitNote, "iterLimitThinkingNote": iterLimitThinkingNote,
	}
	for name, m := range maps {
		for _, l := range locale.Supported {
			if strings.TrimSpace(m[l]) == "" {
				t.Errorf("%s has no %s entry", name, l)
			}
		}
	}
}
