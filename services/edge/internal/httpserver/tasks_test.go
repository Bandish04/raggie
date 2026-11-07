// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/alicangunduz/raggie/services/edge/internal/config"
	"github.com/alicangunduz/raggie/services/edge/internal/ports/mock"
	"github.com/alicangunduz/raggie/services/edge/internal/rag"
)

// extractJSONObject strips a ```fence```, isolates the first balanced {...} block,
// and ignores braces inside quoted strings.
func TestExtractJSONObject(t *testing.T) {
	cases := []struct {
		name, in, want string
	}{
		{"plain", `{"cron":"0 9 * * *"}`, `{"cron":"0 9 * * *"}`},
		{"fenced", "```json\n{\"a\":1}\n```", `{"a":1}`},
		{"preamble", `İşte: {"a":1} bitti`, `{"a":1}`},
		{"brace in string", `{"prompt":"raporu {özet} ver","cron":"0 9 * * *"}`, `{"prompt":"raporu {özet} ver","cron":"0 9 * * *"}`},
		{"nested", `{"a":{"b":1}}`, `{"a":{"b":1}}`},
		{"none", `no json here`, ``},
	}
	for _, c := range cases {
		if got := extractJSONObject(c.in); got != c.want {
			t.Fatalf("%s: extractJSONObject(%q) = %q, want %q", c.name, c.in, got, c.want)
		}
	}
}

// parseScheduleJSON normalises whitespace, trims fields, and REQUIRES exactly 5
// cron fields (else errBadCron).
func TestParseScheduleJSON(t *testing.T) {
	ok, err := parseScheduleJSON("```json\n{\"cron\":\"0  9 * * 1-5\",\"prompt\":\" rapor \",\"name\":\"Günlük\",\"summary\":\"Hafta içi 09:00\"}\n```")
	if err != nil {
		t.Fatalf("expected valid parse, got err %v", err)
	}
	if ok.Cron != "0 9 * * 1-5" {
		t.Fatalf("cron whitespace not normalised: %q", ok.Cron)
	}
	if ok.Prompt != "rapor" {
		t.Fatalf("prompt not trimmed: %q", ok.Prompt)
	}

	// Too few fields → errBadCron.
	if _, err := parseScheduleJSON(`{"cron":"0 9 *","prompt":"x","name":"n","summary":"s"}`); err == nil {
		t.Fatal("expected error for a 3-field cron")
	}
	// Not JSON at all → error.
	if _, err := parseScheduleJSON(`sorry, I cannot`); err == nil {
		t.Fatal("expected error for non-JSON output")
	}
}

// run-task with an UNSET secret is 503 (feature disabled), regardless of the header.
func TestRunTaskDisabledWhenSecretUnset(t *testing.T) {
	srv := New(config.Config{}, discardLogger(), Deps{
		RAG:  rag.New(mock.QueryEmbedder{Dim: 8}, mock.VectorStore{}),
		Chat: mock.ChatProvider{Response: "cevap"},
	})
	req := httptest.NewRequest(http.MethodPost, "/api/v1/internal/run-task",
		strings.NewReader(`{"workspace_id":"w1","prompt":"merhaba"}`))
	req.Header.Set("X-Internal-Secret", "anything")
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("unset secret: expected 503, got %d", rec.Code)
	}
}

// run-task with a WRONG secret is 401; the correct secret runs the pipeline (200).
func TestRunTaskSecretGate(t *testing.T) {
	cfg := config.Config{InternalAPISecret: "s3cr3t", RetrieveCandidateK: 4, RetrieveContextK: 2}
	deps := hotPath(Deps{
		RAG:  rag.New(mock.QueryEmbedder{Dim: 8}, mock.VectorStore{}),
		Chat: mock.ChatProvider{Response: "planlanmış cevap"},
	})
	srv := New(cfg, discardLogger(), deps)

	// Wrong secret → 401.
	bad := httptest.NewRequest(http.MethodPost, "/api/v1/internal/run-task",
		strings.NewReader(`{"workspace_id":"w1","prompt":"merhaba"}`))
	bad.Header.Set("X-Internal-Secret", "wrong")
	rec1 := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec1, bad)
	if rec1.Code != http.StatusUnauthorized {
		t.Fatalf("wrong secret: expected 401, got %d", rec1.Code)
	}

	// Correct secret → 200 with an answer drained from the mock stream.
	good := httptest.NewRequest(http.MethodPost, "/api/v1/internal/run-task",
		strings.NewReader(`{"workspace_id":"w1","user_id":"u1","prompt":"merhaba","answer_style":"short"}`))
	good.Header.Set("X-Internal-Secret", "s3cr3t")
	rec2 := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec2, good)
	if rec2.Code != http.StatusOK {
		t.Fatalf("correct secret: expected 200, got %d (body %s)", rec2.Code, rec2.Body.String())
	}
	if !strings.Contains(rec2.Body.String(), "planlanmış") {
		t.Fatalf("expected drained answer in body, got %s", rec2.Body.String())
	}
}

// run-task rejects an empty prompt with 400 (after the secret check passes).
func TestRunTaskEmptyPrompt(t *testing.T) {
	cfg := config.Config{InternalAPISecret: "s3cr3t"}
	srv := New(cfg, discardLogger(), hotPath(Deps{
		RAG:  rag.New(mock.QueryEmbedder{Dim: 8}, mock.VectorStore{}),
		Chat: mock.ChatProvider{Response: "x"},
	}))
	req := httptest.NewRequest(http.MethodPost, "/api/v1/internal/run-task",
		strings.NewReader(`{"workspace_id":"w1","prompt":"   "}`))
	req.Header.Set("X-Internal-Secret", "s3cr3t")
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("empty prompt: expected 400, got %d", rec.Code)
	}
}

// schedule/parse requires an aud=admin bearer; without it → 401.
func TestScheduleParseRequiresAuth(t *testing.T) {
	srv := New(config.Config{JWTSecret: "k"}, discardLogger(), Deps{Chat: mock.ChatProvider{}})
	req := httptest.NewRequest(http.MethodPost, "/api/v1/schedule/parse",
		strings.NewReader(`{"text":"her gün 9da rapor"}`))
	rec := httptest.NewRecorder()
	srv.Handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("no token: expected 401, got %d", rec.Code)
	}
}

// A scheduled task runs with its owner's authority, so the owner must STILL be
// an active member of the workspace when it fires (removed/deactivated users'
// tasks must stop retrieving that workspace's documents).
func TestRunTaskRechecksOwnerAccess(t *testing.T) {
	cases := map[string]struct {
		access bool
		body   string
		want   int
	}{
		"owner still has access":  {true, `{"workspace_id":"w1","user_id":"u1","prompt":"rapor"}`, http.StatusOK},
		"owner lost access":       {false, `{"workspace_id":"w1","user_id":"u1","prompt":"rapor"}`, http.StatusForbidden},
		"no owner on the request": {true, `{"workspace_id":"w1","prompt":"rapor"}`, http.StatusForbidden},
	}
	for name, tc := range cases {
		t.Run(name, func(t *testing.T) {
			cfg := config.Config{InternalAPISecret: "s3cr3t", RetrieveCandidateK: 4, RetrieveContextK: 2}
			srv := New(cfg, discardLogger(), hotPath(Deps{
				RAG:    rag.New(mock.QueryEmbedder{Dim: 8}, mock.VectorStore{}),
				Chat:   mock.ChatProvider{Response: "cevap"},
				WSInfo: fakeWS{typ: "INTERNAL", access: tc.access},
			}))
			req := httptest.NewRequest(http.MethodPost, "/api/v1/internal/run-task", strings.NewReader(tc.body))
			req.Header.Set("X-Internal-Secret", "s3cr3t")
			rec := httptest.NewRecorder()
			srv.Handler.ServeHTTP(rec, req)
			if rec.Code != tc.want {
				t.Fatalf("expected %d, got %d (%s)", tc.want, rec.Code, rec.Body.String())
			}
		})
	}
}
