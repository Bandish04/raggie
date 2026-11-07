// SPDX-License-Identifier: Apache-2.0

// Package fakestack is a small in-process stand-in for a Raggie stack (the
// control-plane endpoints and the edge chat stream the harnesses use). It backs
// the harness unit tests and every harness's -dry-run mode, so the measurement
// and reporting logic is exercised without docker. Its numbers mean nothing.
package fakestack

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"sort"
	"strings"
	"sync"
	"sync/atomic"
	"time"
	"unicode"
)

// Options shapes the fake's behavior.
type Options struct {
	SetupToken      string        // required by bootstrap when set
	RetrievalDelay  time.Duration // before the SSE headers (the edge's pre-stream work)
	TokenDelay      time.Duration // between streamed tokens
	QueueDelay      time.Duration // PENDING → PROCESSING
	ProcessingDelay time.Duration // PROCESSING → SUCCESS
	MaxConcurrent   int           // concurrent chat streams before 503 busy (0 = unlimited)
	RateLimitAfter  int           // chats per token before 429 rate_limited (0 = off)
	FailFilenames   []string      // uploads with these names end FAILED
	TopK            int           // sources per answer (default 5)
}

// Stack is a running fake: one listener for the control plane, one for the edge.
type Stack struct {
	opts Options
	cp   *httptest.Server
	edge *httptest.Server

	mu         sync.Mutex
	admins     map[string]string // email → password
	tokens     map[string]string // token → email
	orgID      string
	workspaces map[string]string     // id → name
	docs       map[string][]*fakeDoc // workspace id → docs
	chats      map[string]int        // token → chats served

	inflight atomic.Int64
	peak     atomic.Int64
}

type fakeDoc struct {
	ID        string
	Filename  string
	Size      int
	CreatedAt time.Time
	fail      bool
}

// New starts a fake stack. Close it when done.
func New(opts Options) *Stack {
	if opts.TopK <= 0 {
		opts.TopK = 5
	}
	s := &Stack{
		opts:       opts,
		admins:     map[string]string{},
		tokens:     map[string]string{},
		orgID:      newID(),
		workspaces: map[string]string{},
		docs:       map[string][]*fakeDoc{},
		chats:      map[string]int{},
	}
	s.cp = httptest.NewServer(s.cpRoutes())
	s.edge = httptest.NewServer(http.HandlerFunc(s.chat))
	return s
}

func (s *Stack) CPURL() string   { return s.cp.URL }
func (s *Stack) EdgeURL() string { return s.edge.URL }

// PeakConcurrency is the highest number of simultaneously open chat streams.
func (s *Stack) PeakConcurrency() int64 { return s.peak.Load() }

func (s *Stack) Close() {
	s.edge.Close()
	s.cp.Close()
}

// SeedAdmin pre-onboards the stack with a super admin.
func (s *Stack) SeedAdmin(email, password string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.admins[email] = password
}

func newID() string {
	b := make([]byte, 16)
	_, _ = rand.Read(b)
	h := hex.EncodeToString(b)
	return h[0:8] + "-" + h[8:12] + "-" + h[12:16] + "-" + h[16:20] + "-" + h[20:32]
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func (s *Stack) auth(r *http.Request) (string, bool) {
	tok := strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")
	s.mu.Lock()
	defer s.mu.Unlock()
	_, ok := s.tokens[tok]
	return tok, ok
}

func (s *Stack) issue(email string) string {
	tok := newID()
	s.tokens[tok] = email
	return tok
}

func (s *Stack) cpRoutes() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /api/v1/onboarding/state", func(w http.ResponseWriter, _ *http.Request) {
		s.mu.Lock()
		has := len(s.admins) > 0
		s.mu.Unlock()
		writeJSON(w, http.StatusOK, map[string]bool{
			"onboarded": has, "has_super_admin": has, "setup_token_required": !has && s.opts.SetupToken != "",
		})
	})
	mux.HandleFunc("POST /api/v1/onboarding/bootstrap", func(w http.ResponseWriter, r *http.Request) {
		var in map[string]string
		_ = json.NewDecoder(r.Body).Decode(&in)
		s.mu.Lock()
		defer s.mu.Unlock()
		switch {
		case len(s.admins) > 0:
			writeJSON(w, http.StatusConflict, map[string]string{"detail": "already bootstrapped"})
		case s.opts.SetupToken != "" && in["setup_token"] != s.opts.SetupToken:
			writeJSON(w, http.StatusForbidden, map[string]string{"detail": "invalid or missing setup token"})
		case len(in["password"]) < 12:
			writeJSON(w, http.StatusUnprocessableEntity, map[string]string{"detail": "password too short"})
		default:
			s.admins[in["email"]] = in["password"]
			writeJSON(w, http.StatusCreated, map[string]string{"access_token": s.issue(in["email"]), "org_id": s.orgID})
		}
	})
	mux.HandleFunc("POST /api/v1/auth/login", func(w http.ResponseWriter, r *http.Request) {
		var in map[string]string
		_ = json.NewDecoder(r.Body).Decode(&in)
		s.mu.Lock()
		defer s.mu.Unlock()
		if pw, ok := s.admins[in["email"]]; !ok || pw != in["password"] {
			writeJSON(w, http.StatusUnauthorized, map[string]string{"detail": "invalid credentials"})
			return
		}
		writeJSON(w, http.StatusOK, map[string]string{"access_token": s.issue(in["email"])})
	})
	mux.HandleFunc("GET /api/v1/auth/me", func(w http.ResponseWriter, r *http.Request) {
		tok, ok := s.auth(r)
		if !ok {
			writeJSON(w, http.StatusUnauthorized, map[string]string{"detail": "unauthorized"})
			return
		}
		s.mu.Lock()
		email := s.tokens[tok]
		s.mu.Unlock()
		writeJSON(w, http.StatusOK, map[string]any{"id": newID(), "email": email, "org_id": s.orgID, "is_platform_admin": true})
	})
	mux.HandleFunc("POST /api/v1/admin/orgs/{org}/workspaces", func(w http.ResponseWriter, r *http.Request) {
		if _, ok := s.auth(r); !ok || r.PathValue("org") != s.orgID {
			writeJSON(w, http.StatusForbidden, map[string]string{"detail": "forbidden"})
			return
		}
		var in map[string]string
		_ = json.NewDecoder(r.Body).Decode(&in)
		id := newID()
		s.mu.Lock()
		s.workspaces[id] = in["name"]
		s.mu.Unlock()
		writeJSON(w, http.StatusCreated, map[string]string{"id": id, "name": in["name"], "type": in["type"]})
	})
	mux.HandleFunc("POST /api/v1/admin/workspaces/{ws}/documents", func(w http.ResponseWriter, r *http.Request) {
		ws, ok := s.workspace(w, r)
		if !ok {
			return
		}
		f, hdr, err := r.FormFile("file")
		if err != nil {
			writeJSON(w, http.StatusUnprocessableEntity, map[string]string{"detail": "file missing"})
			return
		}
		data, _ := io.ReadAll(f)
		d := &fakeDoc{ID: newID(), Filename: hdr.Filename, Size: len(data), CreatedAt: time.Now().UTC()}
		for _, name := range s.opts.FailFilenames {
			d.fail = d.fail || name == hdr.Filename
		}
		s.mu.Lock()
		s.docs[ws] = append(s.docs[ws], d)
		s.mu.Unlock()
		writeJSON(w, http.StatusCreated, s.docJSON(d))
	})
	mux.HandleFunc("GET /api/v1/admin/workspaces/{ws}/documents", func(w http.ResponseWriter, r *http.Request) {
		ws, ok := s.workspace(w, r)
		if !ok {
			return
		}
		s.mu.Lock()
		out := make([]map[string]any, 0, len(s.docs[ws]))
		for _, d := range s.docs[ws] {
			out = append(out, s.docJSON(d))
		}
		s.mu.Unlock()
		writeJSON(w, http.StatusOK, out)
	})
	return mux
}

func (s *Stack) workspace(w http.ResponseWriter, r *http.Request) (string, bool) {
	if _, ok := s.auth(r); !ok {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"detail": "unauthorized"})
		return "", false
	}
	ws := r.PathValue("ws")
	s.mu.Lock()
	_, ok := s.workspaces[ws]
	s.mu.Unlock()
	if !ok {
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "workspace not found"})
	}
	return ws, ok
}

// docJSON derives the status from elapsed time, like an async worker would.
func (s *Stack) docJSON(d *fakeDoc) map[string]any {
	age := time.Since(d.CreatedAt)
	status, updated := "PENDING", d.CreatedAt
	switch {
	case age >= s.opts.QueueDelay+s.opts.ProcessingDelay:
		status, updated = "SUCCESS", d.CreatedAt.Add(s.opts.QueueDelay+s.opts.ProcessingDelay)
		if d.fail {
			status = "FAILED"
		}
	case age >= s.opts.QueueDelay:
		status, updated = "PROCESSING", d.CreatedAt.Add(s.opts.QueueDelay)
	}
	return map[string]any{
		"id": d.ID, "filename": d.Filename, "file_size": d.Size, "status": status,
		"created_at": d.CreatedAt.Format(time.RFC3339Nano), "updated_at": updated.Format(time.RFC3339Nano),
	}
}

func edgeError(w http.ResponseWriter, status int, code string) {
	writeJSON(w, status, map[string]string{"error": code, "code": code, "message": code})
}

func (s *Stack) chat(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost || r.URL.Path != "/api/v1/chat/stream" {
		edgeError(w, http.StatusNotFound, "not_found")
		return
	}
	tok, ok := s.auth(r)
	if !ok {
		edgeError(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	var in struct {
		WorkspaceID string `json:"workspace_id"`
		Message     string `json:"message"`
	}
	if err := json.NewDecoder(r.Body).Decode(&in); err != nil || in.WorkspaceID == "" || in.Message == "" {
		edgeError(w, http.StatusBadRequest, "bad_request")
		return
	}
	s.mu.Lock()
	s.chats[tok]++
	served := s.chats[tok]
	docs := append([]*fakeDoc(nil), s.docs[in.WorkspaceID]...)
	s.mu.Unlock()
	if s.opts.RateLimitAfter > 0 && served > s.opts.RateLimitAfter {
		w.Header().Set("Retry-After", "60")
		edgeError(w, http.StatusTooManyRequests, "rate_limited")
		return
	}
	n := s.inflight.Add(1)
	defer s.inflight.Add(-1)
	for p := s.peak.Load(); n > p && !s.peak.CompareAndSwap(p, n); p = s.peak.Load() {
	}
	if s.opts.MaxConcurrent > 0 && n > int64(s.opts.MaxConcurrent) {
		w.Header().Set("Retry-After", "1")
		edgeError(w, http.StatusServiceUnavailable, "busy")
		return
	}

	sleep(r, s.opts.RetrievalDelay)
	sources := rank(in.Message, docs, s.opts.TopK)
	w.Header().Set("Content-Type", "text/event-stream")
	flusher, _ := w.(http.Flusher)
	send := func(format string, args ...any) {
		fmt.Fprintf(w, format, args...)
		if flusher != nil {
			flusher.Flush()
		}
	}
	conv, msg := newID(), newID()
	send("event: meta\ndata: {\"conversation_id\":%q,\"message_id\":%q}\n\n", conv, msg)
	srcJSON, _ := json.Marshal(sources)
	send("event: sources\ndata: {\"sources\":%s}\n\n", srcJSON)
	answer := "Bu bilgi kaynaklarda bulunamadı."
	if len(sources) > 0 {
		answer = fmt.Sprintf("Yanıt %s kaynağında yer alıyor [1].", sources[0]["filename"])
	}
	for _, word := range strings.Fields(answer) {
		if !sleep(r, s.opts.TokenDelay) {
			return
		}
		d, _ := json.Marshal(map[string]string{"delta": word + " "})
		send("data: %s\n\n", d)
	}
	send("event: done\ndata: {\"message_id\":%q}\n\n", msg)
	send("data: [DONE]\n\n")
}

func sleep(r *http.Request, d time.Duration) bool {
	if d <= 0 {
		return r.Context().Err() == nil
	}
	select {
	case <-time.After(d):
		return true
	case <-r.Context().Done():
		return false
	}
}

// rank orders documents by how many question words their filename shares —
// enough to give the eval harness non-trivial numbers in a dry run.
func rank(question string, docs []*fakeDoc, k int) []map[string]any {
	q := words(question)
	type scored struct {
		d     *fakeDoc
		score int
	}
	var all []scored
	for _, d := range docs {
		n := 0
		for w := range words(d.Filename) {
			if q[w] {
				n++
			}
		}
		if n > 0 {
			all = append(all, scored{d, n})
		}
	}
	sort.SliceStable(all, func(i, j int) bool { return all[i].score > all[j].score })
	out := make([]map[string]any, 0, min(k, len(all)))
	for i := 0; i < len(all) && i < k; i++ {
		out = append(out, map[string]any{
			"document_id": all[i].d.ID, "filename": all[i].d.Filename, "chunk_index": 0,
			"text": "fake chunk", "score": 1.0 / float64(i+1),
		})
	}
	return out
}

var fold = strings.NewReplacer("ç", "c", "ğ", "g", "ı", "i", "ö", "o", "ş", "s", "ü", "u", "İ", "i")

func words(s string) map[string]bool {
	out := map[string]bool{}
	for _, w := range strings.FieldsFunc(fold.Replace(strings.ToLower(s)), func(r rune) bool {
		return !unicode.IsLetter(r) && !unicode.IsDigit(r)
	}) {
		if len(w) >= 4 {
			out[w] = true
		}
	}
	return out
}
