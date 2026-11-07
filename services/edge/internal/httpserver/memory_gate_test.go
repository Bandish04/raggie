// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/alicangunduz/raggie/services/edge/internal/config"
	"github.com/alicangunduz/raggie/services/edge/internal/locale"
	"github.com/alicangunduz/raggie/services/edge/internal/ports"
	"github.com/alicangunduz/raggie/services/edge/internal/ports/mock"
	"github.com/alicangunduz/raggie/services/edge/internal/rag"
	"github.com/alicangunduz/raggie/services/edge/internal/store"
	"github.com/alicangunduz/raggie/services/edge/internal/widgetauth"
)

const memoryFact = "MEMFACT-42: the user's name is Ada"

// fakeMemory records reads (injection) and writes (extraction).
type fakeMemory struct {
	mu    sync.Mutex
	gets  int
	added [][]string
}

func (m *fakeMemory) GetUserMemory(context.Context, string, int) ([]string, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.gets++
	return []string{memoryFact}, nil
}

func (m *fakeMemory) AddUserMemory(_ context.Context, _ string, facts []string) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.added = append(m.added, facts)
	return nil
}

func (m *fakeMemory) counts() (int, int) {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.gets, len(m.added)
}

type fakeFeatures struct {
	flags store.WorkspaceFeatureFlags
	err   error
}

func (f fakeFeatures) WorkspaceFeatures(context.Context, string) (store.WorkspaceFeatureFlags, error) {
	return f.flags, f.err
}

// memoryChat answers chat turns and memory-extraction calls, recording every
// request so a test can see whether memory reached the prompt.
type memoryChat struct {
	mu   sync.Mutex
	reqs []ports.ChatRequest
}

func (c *memoryChat) Stream(_ context.Context, req ports.ChatRequest) (<-chan ports.ChatChunk, error) {
	c.mu.Lock()
	c.reqs = append(c.reqs, req)
	c.mu.Unlock()
	reply := "Paris."
	if len(req.Messages) > 0 && isExtractionPrompt(req.Messages[0].Content) {
		reply = "- The user's name is Ada."
	}
	ch := make(chan ports.ChatChunk, 2)
	ch <- ports.ChatChunk{Delta: reply}
	ch <- ports.ChatChunk{Done: true, FinishReason: "stop"}
	close(ch)
	return ch, nil
}

func isExtractionPrompt(s string) bool {
	return s == locale.Pick(memoryExtractionPrompt, locale.EN) || s == locale.Pick(memoryExtractionPrompt, locale.TR)
}

// injected reports whether any non-extraction request carried the memory fact.
func (c *memoryChat) injected() bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	for _, r := range c.reqs {
		if len(r.Messages) > 0 && isExtractionPrompt(r.Messages[0].Content) {
			continue
		}
		for _, m := range r.Messages {
			if strings.Contains(m.Content, "MEMFACT-42") {
				return true
			}
		}
	}
	return false
}

type memoryCase struct {
	name          string
	globalOn      bool
	flags         store.WorkspaceFeatureFlags
	flagsErr      error
	widget        bool // anonymous EXTERNAL widget session instead of an admin user
	wantInjected  bool
	wantExtracted bool
}

func memoryCases() []memoryCase {
	on := store.WorkspaceFeatureFlags{Memory: true}
	return []memoryCase{
		{name: "all on", globalOn: true, flags: on, wantInjected: true, wantExtracted: true},
		{name: "global kill switch off", globalOn: false, flags: on},
		{name: "workspace flag off", globalOn: true, flags: store.WorkspaceFeatureFlags{}},
		{name: "feature read fails (fail closed)", globalOn: true, flags: on, flagsErr: errors.New("column memory_enabled does not exist")},
		{name: "anonymous widget session", globalOn: true, flags: on, widget: true},
	}
}

func memoryDeps(mem *fakeMemory, chat *memoryChat, tc memoryCase) Deps {
	vs := mock.VectorStore{Chunks: []ports.Chunk{{DocumentID: "d1", Filename: "geo.txt", Text: "Paris.", Score: 0.9}}}
	typ := "INTERNAL"
	if tc.widget {
		typ = "EXTERNAL"
	}
	return Deps{
		RAG:        rag.New(mock.QueryEmbedder{Dim: 8}, vs),
		Chat:       chat,
		WSInfo:     fakeWS{typ: typ, cors: []string{"https://acme.example"}, access: true},
		Memory:     mem,
		Features:   fakeFeatures{flags: tc.flags, err: tc.flagsErr},
		Background: NewBackgroundJobs(2, 5*time.Second, discardLogger()),
	}
}

func memoryChatRequest(t *testing.T, tc memoryCase) *http.Request {
	req := httptest.NewRequest(http.MethodPost, "/api/v1/chat/stream",
		strings.NewReader(`{"workspace_id":"ws1","message":"What is the capital of France?"}`))
	if tc.widget {
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

// Memory is injected and extracted only when the global kill switch, the
// per-workspace flag and an authenticated user all agree — on both the legacy
// and the unified agentic loop.
func TestChatMemoryGates(t *testing.T) {
	for _, unified := range []bool{false, true} {
		for _, tc := range memoryCases() {
			name := tc.name
			if unified {
				name = "unified/" + name
			}
			t.Run(name, func(t *testing.T) {
				mem, chat := &fakeMemory{}, &memoryChat{}
				deps := memoryDeps(mem, chat, tc)
				cfg := widgetCfg()
				cfg.MemoryEnabled = tc.globalOn
				cfg.AgentUnifiedLoop, cfg.AgentMaxIterations = unified, 4
				srv := New(cfg, discardLogger(), deps)

				rec := httptest.NewRecorder()
				srv.Handler.ServeHTTP(rec, memoryChatRequest(t, tc))
				if rec.Code != http.StatusOK || !strings.Contains(rec.Body.String(), "[DONE]") {
					t.Fatalf("chat: %d %s", rec.Code, rec.Body.String())
				}
				// Wait for the background extraction job, if one was scheduled.
				ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
				defer cancel()
				if err := deps.Background.Shutdown(ctx); err != nil {
					t.Fatal(err)
				}

				gets, adds := mem.counts()
				if got := chat.injected(); got != tc.wantInjected {
					t.Errorf("memory injected into the prompt = %v, want %v", got, tc.wantInjected)
				}
				if tc.wantInjected != (gets > 0) {
					t.Errorf("memory reads = %d, want any=%v", gets, tc.wantInjected)
				}
				if got := adds > 0; got != tc.wantExtracted {
					t.Errorf("memory extracted and stored = %v, want %v", got, tc.wantExtracted)
				}
			})
		}
	}
}

// Scheduled tasks only ever read memory (never extract), under the same gates.
func TestRunTaskMemoryGates(t *testing.T) {
	for _, tc := range memoryCases() {
		if tc.widget {
			continue // run-task has no widget surface
		}
		t.Run(tc.name, func(t *testing.T) {
			mem, chat := &fakeMemory{}, &memoryChat{}
			deps := memoryDeps(mem, chat, tc)
			cfg := config.Config{InternalAPISecret: "s3cr3t", MemoryEnabled: tc.globalOn, RetrieveCandidateK: 4, RetrieveContextK: 2}
			srv := New(cfg, discardLogger(), deps)

			req := httptest.NewRequest(http.MethodPost, "/api/v1/internal/run-task",
				strings.NewReader(`{"workspace_id":"ws1","user_id":"user-1","prompt":"summarise"}`))
			req.Header.Set("X-Internal-Secret", "s3cr3t")
			rec := httptest.NewRecorder()
			srv.Handler.ServeHTTP(rec, req)
			if rec.Code != http.StatusOK {
				t.Fatalf("run-task: %d %s", rec.Code, rec.Body.String())
			}
			ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
			defer cancel()
			_ = deps.Background.Shutdown(ctx)

			if got := chat.injected(); got != tc.wantInjected {
				t.Errorf("memory injected = %v, want %v", got, tc.wantInjected)
			}
			if _, adds := mem.counts(); adds != 0 {
				t.Errorf("a scheduled run must never extract memory (stored %d batches)", adds)
			}
		})
	}
}
