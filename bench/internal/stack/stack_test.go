// SPDX-License-Identifier: Apache-2.0

package stack

import (
	"context"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/alicangunduz/raggie/bench/internal/fakestack"
)

func cfgFor(fs *fakestack.Stack, t *testing.T) Config {
	return Config{CPURL: fs.CPURL(), EdgeURL: fs.EdgeURL(), StateDir: t.TempDir()}
}

func TestConnectBootstrapsFreshStackAndRemembersCredentials(t *testing.T) {
	fs := fakestack.New(fakestack.Options{SetupToken: "setup-123"})
	defer fs.Close()
	cfg := cfgFor(fs, t)

	cfg.SetupToken = ""
	if _, err := Connect(context.Background(), cfg); err == nil || !strings.Contains(err.Error(), "setup token") {
		t.Fatalf("fresh stack without a setup token: err = %v", err)
	}

	cfg.SetupToken = "setup-123"
	s, err := Connect(context.Background(), cfg)
	if err != nil {
		t.Fatal(err)
	}
	if !s.Bootstrapped || s.Me.OrgID == "" || s.Token == "" {
		t.Fatalf("session = %+v", s)
	}
	info, err := os.Stat(filepath.Join(cfg.StateDir, "admin.json"))
	if err != nil || info.Mode().Perm() != 0o600 {
		t.Fatalf("credentials file: %v, mode %v", err, info)
	}

	// A second run logs in with the remembered credentials.
	again, err := Connect(context.Background(), cfg)
	if err != nil {
		t.Fatal(err)
	}
	if again.Bootstrapped || again.Me.OrgID != s.Me.OrgID {
		t.Fatalf("second session = %+v", again)
	}
}

func TestConnectFallsBackToWebE2EState(t *testing.T) {
	fs := fakestack.New(fakestack.Options{})
	defer fs.Close()
	fs.SeedAdmin("e2e@e2e.raggie.test", "E2e-strong-password")
	root := t.TempDir()
	stateDir := filepath.Join(root, "web", "e2e", "stack", ".state")
	if err := os.MkdirAll(stateDir, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(stateDir, "stack.json"),
		[]byte(`{"adminEmail":"e2e@e2e.raggie.test","adminPassword":"E2e-strong-password"}`), 0o600); err != nil {
		t.Fatal(err)
	}
	cfg := cfgFor(fs, t)

	if _, err := Connect(context.Background(), cfg); err == nil || !strings.Contains(err.Error(), "RAGGIE_BENCH_EMAIL") {
		t.Fatalf("onboarded stack without credentials: err = %v", err)
	}
	cfg.RepoRoot = root
	if _, err := Connect(context.Background(), cfg); err != nil {
		t.Fatalf("web e2e state fallback: %v", err)
	}
}

func TestUploadAndWaitObservesTransitions(t *testing.T) {
	fs := fakestack.New(fakestack.Options{QueueDelay: 30 * time.Millisecond, ProcessingDelay: 60 * time.Millisecond,
		FailFilenames: []string{"bad.pdf"}})
	defer fs.Close()
	s, err := Connect(context.Background(), cfgFor(fs, t))
	if err != nil {
		t.Fatal(err)
	}
	ctx := context.Background()
	ws, err := s.CreateWorkspace(ctx, s.Me.OrgID, "bench")
	if err != nil {
		t.Fatal(err)
	}
	good, err := s.Upload(ctx, ws.ID, "good.pdf", []byte("%PDF"))
	if err != nil {
		t.Fatal(err)
	}
	bad, err := s.Upload(ctx, ws.ID, "bad.pdf", []byte("%PDF"))
	if err != nil {
		t.Fatal(err)
	}
	seen := map[string][]string{}
	final, err := s.WaitDocuments(ctx, ws.ID, []string{good.ID, bad.ID}, 5*time.Millisecond, func(d Document, _ time.Time) {
		seen[d.Filename] = append(seen[d.Filename], d.Status)
	})
	if err != nil {
		t.Fatal(err)
	}
	if final[good.ID].Status != StatusSuccess || final[bad.ID].Status != StatusFailed {
		t.Fatalf("final = %+v", final)
	}
	if got := strings.Join(seen["good.pdf"], ">"); got != "PENDING>PROCESSING>SUCCESS" {
		t.Fatalf("observed transitions = %s", got)
	}
	if d := final[good.ID]; d.UpdatedAt.Sub(d.CreatedAt) < 90*time.Millisecond {
		t.Fatalf("server-side duration = %s", d.UpdatedAt.Sub(d.CreatedAt))
	}
}

func TestWaitDocumentsHonorsContext(t *testing.T) {
	fs := fakestack.New(fakestack.Options{QueueDelay: time.Hour})
	defer fs.Close()
	s, _ := Connect(context.Background(), cfgFor(fs, t))
	ws, _ := s.CreateWorkspace(context.Background(), s.Me.OrgID, "bench")
	d, _ := s.Upload(context.Background(), ws.ID, "slow.pdf", []byte("x"))
	ctx, cancel := context.WithTimeout(context.Background(), 50*time.Millisecond)
	defer cancel()
	if _, err := s.WaitDocuments(ctx, ws.ID, []string{d.ID}, 5*time.Millisecond, nil); err == nil {
		t.Fatal("expected a timeout")
	}
}

func TestChatRecordsPhasesInOrder(t *testing.T) {
	fs := fakestack.New(fakestack.Options{RetrievalDelay: 20 * time.Millisecond, TokenDelay: 5 * time.Millisecond})
	defer fs.Close()
	s, _ := Connect(context.Background(), cfgFor(fs, t))
	ctx := context.Background()
	ws, _ := s.CreateWorkspace(ctx, s.Me.OrgID, "bench")
	if _, err := s.Upload(ctx, ws.ID, "Izin_Politikasi_2026.md", []byte("x")); err != nil {
		t.Fatal(err)
	}

	r := s.Chat(ctx, ChatRequest{WorkspaceID: ws.ID, Message: "izin politikasi nedir"})
	if !r.OK() || r.Outcome() != "ok" {
		t.Fatalf("result = %+v (%s)", r, r.Outcome())
	}
	if r.Headers < 20*time.Millisecond {
		t.Fatalf("headers at %s, want >= the pre-stream delay", r.Headers)
	}
	if !(r.Headers <= r.Meta && r.Meta <= r.Sources && r.Sources < r.FirstToken && r.FirstToken < r.Done && r.Done <= r.Total) {
		t.Fatalf("phases out of order: %+v", r)
	}
	if len(r.SourceList) != 1 || r.SourceList[0].Filename != "Izin_Politikasi_2026.md" {
		t.Fatalf("sources = %+v", r.SourceList)
	}
	if r.Conversation == "" || r.MessageID == "" || r.Tokens == 0 || !strings.Contains(r.Answer, "[1]") {
		t.Fatalf("result = %+v", r)
	}
}

func TestChatClassifiesFailures(t *testing.T) {
	fs := fakestack.New(fakestack.Options{RateLimitAfter: 1})
	defer fs.Close()
	s, _ := Connect(context.Background(), cfgFor(fs, t))
	ws, _ := s.CreateWorkspace(context.Background(), s.Me.OrgID, "bench")
	_ = s.Chat(context.Background(), ChatRequest{WorkspaceID: ws.ID, Message: "q"})
	r := s.Chat(context.Background(), ChatRequest{WorkspaceID: ws.ID, Message: "q"})
	if r.OK() || r.Status != http.StatusTooManyRequests || r.ErrorCode != "rate_limited" {
		t.Fatalf("result = %+v", r)
	}
	if r.Outcome() != "http_Too Many Requests:rate_limited" {
		t.Fatalf("outcome = %q", r.Outcome())
	}

	// A stream that ends with an SSE error event is not a success.
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		_, _ = w.Write([]byte("event: meta\ndata: {}\n\nevent: error\ndata: {\"code\":\"stream_error\"}\n\ndata: [DONE]\n\n"))
	}))
	defer srv.Close()
	c := NewClient(srv.URL, srv.URL, 1)
	r = c.Chat(context.Background(), ChatRequest{WorkspaceID: "w", Message: "q"})
	if r.OK() || r.Outcome() != "stream_error:stream_error" {
		t.Fatalf("outcome = %q (%+v)", r.Outcome(), r)
	}

	// Unreachable edge → transport error, never a panic.
	dead := NewClient("http://127.0.0.1:1", "http://127.0.0.1:1", 1)
	r = dead.Chat(context.Background(), ChatRequest{WorkspaceID: "w", Message: "q"})
	if r.Outcome() != "transport_error" {
		t.Fatalf("outcome = %q", r.Outcome())
	}
}
