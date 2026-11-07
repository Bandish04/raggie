// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/alicangunduz/raggie/services/edge/internal/config"
	"github.com/alicangunduz/raggie/services/edge/internal/locale"
)

type errorBody struct {
	Error   string `json:"error"`
	Code    string `json:"code"`
	Message string `json:"message"`
}

func decodeError(t *testing.T, rec *httptest.ResponseRecorder) errorBody {
	t.Helper()
	if ct := rec.Header().Get("Content-Type"); !strings.HasPrefix(ct, "application/json") {
		t.Fatalf("error responses must be JSON, got Content-Type %q: %s", ct, rec.Body.String())
	}
	var b errorBody
	if err := json.Unmarshal(rec.Body.Bytes(), &b); err != nil {
		t.Fatalf("decode error body: %v (%s)", err, rec.Body.String())
	}
	return b
}

// Every code has a non-empty English and Turkish message.
func TestErrorCatalogIsComplete(t *testing.T) {
	for code, msgs := range errMessages {
		for _, l := range locale.Supported {
			if strings.TrimSpace(msgs[l]) == "" {
				t.Errorf("code %q has no %s message", code, l)
			}
		}
	}
}

// Pre-stream chat errors keep the legacy {"error","message"} shape and add a
// stable "code" (== "error"); the message defaults to English and follows the
// request locale (Accept-Language, then an explicit locale field).
func TestChatErrorShapeAndLocale(t *testing.T) {
	srv := New(testCfg(), discardLogger(), mockDeps())
	cases := []struct {
		name, acceptLang, body string
		wantLang               locale.Locale
	}{
		{"english default", "", `{"workspace_id":"ws1"}`, locale.EN},
		{"accept-language tr", "tr-TR,tr;q=0.9", `{"workspace_id":"ws1"}`, locale.TR},
		{"explicit locale field wins", "en-US", `{"workspace_id":"ws1","locale":"tr"}`, locale.TR},
	}
	for _, tc := range cases {
		req := httptest.NewRequest(http.MethodPost, "/api/v1/chat/stream", strings.NewReader(tc.body))
		if tc.acceptLang != "" {
			req.Header.Set("Accept-Language", tc.acceptLang)
		}
		rec := httptest.NewRecorder()
		srv.Handler.ServeHTTP(rec, req)
		if rec.Code != http.StatusBadRequest {
			t.Fatalf("%s: expected 400, got %d", tc.name, rec.Code)
		}
		b := decodeError(t, rec)
		if b.Error != errCodeBadRequest || b.Code != errCodeBadRequest {
			t.Fatalf("%s: error/code = %q/%q, want %q", tc.name, b.Error, b.Code, errCodeBadRequest)
		}
		if want := errMessages[errCodeBadRequest][tc.wantLang]; b.Message != want {
			t.Fatalf("%s: message = %q, want %q", tc.name, b.Message, want)
		}
	}
}

func TestDefaultLocaleConfigDrivesMessages(t *testing.T) {
	cfg := testCfg()
	cfg.DefaultLocale = locale.TR
	srv := New(cfg, discardLogger(), mockDeps())
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, httptest.NewRequest(http.MethodPost, "/api/v1/chat/stream", strings.NewReader(`{}`)))
	if b := decodeError(t, rec); b.Message != errMessages[errCodeBadRequest][locale.TR] {
		t.Fatalf("DEFAULT_LOCALE=tr should yield the Turkish message, got %q", b.Message)
	}
}

// Mid-stream SSE errors carry the code too.
func TestStreamErrorEventCarriesCode(t *testing.T) {
	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/", nil)
	writeStreamError(rec, req, errCodeStream)
	out := rec.Body.String()
	if !strings.HasPrefix(out, "event: error\ndata: ") {
		t.Fatalf("unexpected SSE frame: %q", out)
	}
	var b errorBody
	if err := json.Unmarshal([]byte(strings.TrimSpace(strings.TrimPrefix(out, "event: error\ndata: "))), &b); err != nil {
		t.Fatal(err)
	}
	if b.Code != errCodeStream || b.Message != errMessages[errCodeStream][locale.EN] {
		t.Fatalf("stream error = %+v", b)
	}
}

// Non-chat endpoints used to answer with text/plain bodies; they now share
// the JSON error shape (status codes unchanged).
func TestNonChatEndpointsReturnJSONErrors(t *testing.T) {
	deps := mockDeps()
	deps.WSInfo = fakeWS{typ: "INTERNAL"}
	srv := newSrv(t, deps)
	cases := []struct {
		method, path, body, origin string
		status                     int
		code                       string
	}{
		{http.MethodPost, "/api/v1/widget/token", `{"workspace_id":"` + widgetWS + `"}`, "https://acme.example", http.StatusNotFound, errCodeNotFound},
		{http.MethodPost, "/api/v1/widget/token", `{}`, "https://acme.example", http.StatusBadRequest, errCodeBadRequest},
		{http.MethodGet, "/api/v1/admin/mcp/capabilities", "", "", http.StatusUnauthorized, errCodeUnauth},
		{http.MethodPost, "/api/v1/schedule/parse", `{"text":"x"}`, "", http.StatusUnauthorized, errCodeUnauth},
	}
	for _, tc := range cases {
		req := httptest.NewRequest(tc.method, tc.path, strings.NewReader(tc.body))
		if tc.origin != "" {
			req.Header.Set("Origin", tc.origin)
		}
		req.Header.Set("Accept-Language", "tr")
		rec := httptest.NewRecorder()
		srv.Handler.ServeHTTP(rec, req)
		if rec.Code != tc.status {
			t.Fatalf("%s %s: status %d, want %d", tc.method, tc.path, rec.Code, tc.status)
		}
		b := decodeError(t, rec)
		if b.Code != tc.code || b.Error != tc.code || b.Message != errMessages[tc.code][locale.TR] {
			t.Fatalf("%s %s: body %+v, want code %q with the Turkish message", tc.method, tc.path, b, tc.code)
		}
	}
}

func TestMetricsUnauthorizedIsJSON(t *testing.T) {
	srv := NewMetricsServer(config.Config{MetricsToken: "t"}, discardLogger(), Deps{})
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/metrics", nil))
	if b := decodeError(t, rec); rec.Code != http.StatusUnauthorized || b.Code != errCodeUnauth {
		t.Fatalf("metrics 401 body %+v", b)
	}
}
