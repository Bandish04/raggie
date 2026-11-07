// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"encoding/base64"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/alicangunduz/raggie/services/edge/internal/widgetauth"
)

// 1x1 transparent PNG.
var tinyPNG = "data:image/png;base64," + base64.StdEncoding.EncodeToString([]byte{
	0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00, 0x00, 0x00, 0x0d, 0x49, 0x48, 0x44, 0x52,
})

func TestValidAttachment(t *testing.T) {
	big := "data:image/png;base64," + strings.Repeat("A", maxAttachBytes)
	for name, tc := range map[string]struct {
		a    attachment
		want bool
	}{
		"png":                {attachment{Type: "image", DataURL: tinyPNG}, true},
		"jpeg":               {attachment{Type: "image", DataURL: "data:image/jpeg;base64,/9j/4AAQ"}, true},
		"webp":               {attachment{Type: "image", DataURL: "data:image/webp;base64,UklGRg=="}, true},
		"gif":                {attachment{Type: "image", DataURL: "data:image/gif;base64,R0lGODlh"}, true},
		"metadata endpoint":  {attachment{Type: "image", DataURL: "http://169.254.169.254/latest/meta-data/"}, false},
		"https url":          {attachment{Type: "image", DataURL: "https://attacker.example/x.png"}, false},
		"file url":           {attachment{Type: "image", DataURL: "file:///etc/passwd"}, false},
		"svg (scriptable)":   {attachment{Type: "image", DataURL: "data:image/svg+xml;base64,PHN2Zz4="}, false},
		"not base64":         {attachment{Type: "image", DataURL: "data:image/png;base64,not*base64!"}, false},
		"missing base64 tag": {attachment{Type: "image", DataURL: "data:image/png,rawbytes"}, false},
		"empty payload":      {attachment{Type: "image", DataURL: "data:image/png;base64,"}, false},
		"upper-case scheme":  {attachment{Type: "image", DataURL: "DATA:image/png;base64,AAAA"}, false},
		"url smuggled after": {attachment{Type: "image", DataURL: "data:image/png;base64,AAAA http://169.254.169.254/"}, false},
		"wrong type":         {attachment{Type: "file", DataURL: tinyPNG}, false},
		"too large":          {attachment{Type: "image", DataURL: big}, false},
	} {
		if got := validAttachment(tc.a); got != tc.want {
			t.Errorf("%s: validAttachment = %v, want %v", name, got, tc.want)
		}
	}
}

func attachmentChatRequest(t *testing.T, widget bool, dataURL string) *http.Request {
	t.Helper()
	body, err := json.Marshal(map[string]any{
		"workspace_id": "ws1",
		"message":      "What is in this picture?",
		"model":        "vision-1",
		"attachments":  []map[string]string{{"type": "image", "data_url": dataURL}},
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

// A URL attachment would make an OpenAI-compatible server (vLLM, LiteLLM)
// fetch it: SSRF from an anonymous widget visitor. Anything but an inline
// raster data URL is refused with 400 before the model is called, on both
// loops and for both principals; a valid image still reaches the model.
func TestChatRejectsNonDataImageAttachments(t *testing.T) {
	for _, unified := range []bool{false, true} {
		for _, widget := range []bool{false, true} {
			name := map[bool]string{false: "legacy", true: "unified"}[unified] + "-" +
				map[bool]string{false: "internal", true: "widget"}[widget]
			t.Run(name, func(t *testing.T) {
				run := func(dataURL string) (*httptest.ResponseRecorder, *memoryChat) {
					chat := &memoryChat{}
					deps := memoryDeps(&fakeMemory{}, chat, memoryCase{widget: widget})
					deps.Memory = nil
					cfg := widgetCfg()
					cfg.VisionModels = map[string]bool{"vision-1": true}
					cfg.AgentUnifiedLoop, cfg.AgentMaxIterations = unified, 4
					rec := httptest.NewRecorder()
					New(cfg, discardLogger(), deps).Handler.ServeHTTP(rec, attachmentChatRequest(t, widget, dataURL))
					return rec, chat
				}

				rec, chat := run("http://169.254.169.254/latest/meta-data/iam/security-credentials/")
				if rec.Code != http.StatusBadRequest || !strings.Contains(rec.Body.String(), `"bad_request"`) {
					t.Fatalf("URL attachment: %d %s, want 400 bad_request", rec.Code, rec.Body.String())
				}
				if len(chat.reqs) != 0 {
					t.Fatalf("the model was called %d time(s) for a rejected request", len(chat.reqs))
				}

				rec, chat = run(tinyPNG)
				if rec.Code != http.StatusOK {
					t.Fatalf("valid image: %d %s", rec.Code, rec.Body.String())
				}
				seen := false
				for _, r := range chat.reqs {
					for _, m := range r.Messages {
						for _, p := range m.Parts {
							if p.ImageURL != nil && p.ImageURL.URL == tinyPNG {
								seen = true
							}
						}
					}
				}
				if !seen {
					t.Fatal("a valid data:image attachment did not reach the vision model")
				}
			})
		}
	}
}
