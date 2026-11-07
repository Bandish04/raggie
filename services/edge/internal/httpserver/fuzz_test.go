// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"net/netip"
	"strings"
	"testing"
	"unicode/utf8"

	"github.com/alicangunduz/raggie/services/edge/internal/config"
	"github.com/alicangunduz/raggie/services/edge/internal/ports/mock"
	"github.com/alicangunduz/raggie/services/edge/internal/rag"
)

// countingReader records how many bytes the decoder pulled from the body.
type countingReader struct {
	r io.Reader
	n int
}

func (c *countingReader) Read(p []byte) (int, error) {
	n, err := c.r.Read(p)
	c.n += n
	return n, err
}

// decodeJSONBody never reads past its cap (+1 byte to detect overflow) and
// only reports errBodyTooLarge when the body really exceeds it.
func FuzzDecodeJSONBody(f *testing.F) {
	f.Add([]byte(`{"workspace_id":"w","message":"hi"}`), uint16(64))
	f.Add([]byte(`{"a":"`+strings.Repeat("x", 200)+`"}`), uint16(16))
	f.Add([]byte(`   {}   trailing`), uint16(4))
	f.Fuzz(func(t *testing.T, body []byte, limit uint16) {
		if limit == 0 {
			return
		}
		cr := &countingReader{r: bytes.NewReader(body)}
		req := httptest.NewRequest(http.MethodPost, "/", cr)
		var v map[string]any
		err := decodeJSONBody(httptest.NewRecorder(), req, int64(limit), &v)
		if cr.n > int(limit)+1 {
			t.Fatalf("read %d bytes with a cap of %d", cr.n, limit)
		}
		if errors.Is(err, errBodyTooLarge) && len(body) <= int(limit) {
			t.Fatalf("errBodyTooLarge for a %d-byte body under a %d cap", len(body), limit)
		}
	})
}

// fuzzServers builds the public mux once per fuzz target.
func fuzzChatServer() *http.Server {
	cfg := testCfg()
	cfg.ChatMaxBodyBytes = 8 << 10
	return New(cfg, discardLogger(), mockDeps())
}

// assertErrorContract: never a 5xx from a malformed request, and every error
// body follows the JSON contract.
func assertErrorContract(t *testing.T, rec *httptest.ResponseRecorder) {
	t.Helper()
	if rec.Code >= 500 {
		t.Fatalf("server error %d: %s", rec.Code, rec.Body.String())
	}
	if rec.Code >= 400 {
		var b struct{ Error, Code, Message string }
		if json.Unmarshal(rec.Body.Bytes(), &b) != nil || b.Code == "" || b.Error != b.Code || b.Message == "" {
			t.Fatalf("error body breaks the contract: %d %s", rec.Code, rec.Body.String())
		}
	}
}

func FuzzChatRequest(f *testing.F) {
	f.Add(`{"workspace_id":"ws1","message":"hi"}`, "tr-TR,tr;q=0.9")
	f.Add(`{"workspace_id":"ws1","message":"hi","workspace_ids":["a","b"],"locale":"en","attachments":[{"type":"image","data_url":"data:x"}]}`, "")
	f.Add(`{"workspace_id":"ws1","message":"hi","skill_version":3}`, "*")
	f.Add(`{"workspace_id":1}`, "en;q=abc")
	srv := fuzzChatServer()
	f.Fuzz(func(t *testing.T, body, acceptLang string) {
		req := httptest.NewRequest(http.MethodPost, "/api/v1/chat/stream", strings.NewReader(body))
		req.Header.Set("Accept-Language", acceptLang)
		rec := httptest.NewRecorder()
		srv.Handler.ServeHTTP(rec, req)
		assertErrorContract(t, rec)
	})
}

func FuzzWidgetTokenRequest(f *testing.F) {
	f.Add(`{"workspace_id":"wsX"}`, "https://acme.example")
	f.Add(`{"workspace_id":"missing"}`, "")
	f.Add(`not json`, "null")
	deps := mockDeps()
	deps.WSInfo = fakeWS{typ: "EXTERNAL", cors: []string{"https://acme.example"}}
	srv := New(widgetCfg(), discardLogger(), deps)
	f.Fuzz(func(t *testing.T, body, origin string) {
		req := httptest.NewRequest(http.MethodPost, "/api/v1/widget/token", strings.NewReader(body))
		req.Header.Set("Origin", origin)
		rec := httptest.NewRecorder()
		srv.Handler.ServeHTTP(rec, req)
		assertErrorContract(t, rec)
		if rec.Code == http.StatusOK && origin != "https://acme.example" {
			t.Fatalf("token issued to origin %q", origin)
		}
	})
}

func FuzzRunTaskRequest(f *testing.F) {
	f.Add(`{"workspace_id":"w1","user_id":"u1","prompt":"report","model":"m","answer_style":"short"}`)
	f.Add(`{"workspace_id":"w1","prompt":"   "}`)
	f.Add(`[]`)
	cfg := config.Config{InternalAPISecret: "s3cr3t", RetrieveCandidateK: 4, RetrieveContextK: 2}
	srv := New(cfg, discardLogger(), hotPath(Deps{
		RAG:  rag.New(mock.QueryEmbedder{Dim: 8}, mock.VectorStore{}),
		Chat: mock.ChatProvider{Response: "ok"},
	}))
	f.Fuzz(func(t *testing.T, body string) {
		req := httptest.NewRequest(http.MethodPost, "/api/v1/internal/run-task", strings.NewReader(body))
		req.Header.Set("X-Internal-Secret", "s3cr3t")
		rec := httptest.NewRecorder()
		srv.Handler.ServeHTTP(rec, req)
		assertErrorContract(t, rec)
	})
}

// clientIP never trusts X-Forwarded-For from an untrusted peer and only ever
// returns the peer or one of the forwarded hops.
func FuzzClientIP(f *testing.F) {
	f.Add("10.1.2.3:80", "198.51.100.1, 10.9.9.9", true)
	f.Add("203.0.113.9:1234", "1.2.3.4", true)
	f.Add("[::1]:443", "::ffff:8.8.8.8", false)
	f.Add("garbage", "", true)
	trusted := []netip.Prefix{netip.MustParsePrefix("10.0.0.0/8"), netip.MustParsePrefix("::1/128")}
	f.Fuzz(func(t *testing.T, remote, xff string, useTrusted bool) {
		req := httptest.NewRequest(http.MethodGet, "/", nil)
		req.RemoteAddr = remote
		req.Header.Set("X-Forwarded-For", xff)
		var tp []netip.Prefix
		if useTrusted {
			tp = trusted
		}
		got := clientIP(req, tp)
		peerHost := remote
		if h, _, err := net.SplitHostPort(remote); err == nil {
			peerHost = h
		}
		peer, err := netip.ParseAddr(peerHost)
		if err != nil {
			if got != peerHost {
				t.Fatalf("unparseable peer %q: got %q", remote, got)
			}
			return
		}
		peer = peer.Unmap()
		if !isTrustedProxy(peer, tp) {
			if got != peer.String() {
				t.Fatalf("untrusted peer %s: XFF must be ignored, got %q", peer, got)
			}
			return
		}
		if got == peer.String() {
			return
		}
		for _, hop := range strings.Split(xff, ",") {
			if a, err := netip.ParseAddr(strings.TrimSpace(hop)); err == nil && a.Unmap().String() == got {
				return
			}
		}
		t.Fatalf("clientIP returned %q, neither the peer nor a forwarded hop", got)
	})
}

// extractJSONObject returns "" or a balanced {...} substring of its input.
func FuzzExtractJSONObject(f *testing.F) {
	for _, s := range []string{"```json\n{\"a\":1}\n```", `x {"b":"}"} y`, `{{{`, `"{"`, `{"a":"\"}"}`} {
		f.Add(s)
	}
	f.Fuzz(func(t *testing.T, raw string) {
		got := extractJSONObject(raw)
		if got == "" {
			return
		}
		if got[0] != '{' || got[len(got)-1] != '}' || !strings.Contains(raw, got) {
			t.Fatalf("extractJSONObject(%q) = %q", raw, got)
		}
	})
}

func FuzzParseScheduleJSON(f *testing.F) {
	f.Add(`{"cron":"0 9 * * 1-5","prompt":"p","name":"n","summary":"s"}`)
	f.Add("```json\n{\"cron\":\"0  9 *\"}\n```")
	f.Fuzz(func(t *testing.T, raw string) {
		out, err := parseScheduleJSON(raw)
		if err == nil && len(strings.Fields(out.Cron)) != 5 {
			t.Fatalf("accepted cron %q", out.Cron)
		}
	})
}

// Query/marker cleaners keep their size and shape guarantees.
func FuzzQueryCleaners(f *testing.F) {
	f.Add("1. izin politikası\n- remote\n\"izin politikası\"", "şirket izin politikası", 4)
	f.Add(`{"queries":["a","b"]}`, "q", 2)
	f.Add("query: \"x\"", "", 1)
	f.Fuzz(func(t *testing.T, raw, question string, max int) {
		if max < 1 || max > 64 {
			return
		}
		qs := parseSubQueries(raw, question, max)
		if len(qs) > max {
			t.Fatalf("parseSubQueries returned %d > %d", len(qs), max)
		}
		seen := map[string]bool{}
		for i, q := range qs {
			k := strings.ToLower(q)
			if q == "" || seen[k] {
				t.Fatalf("empty or duplicate query %q", q)
			}
			seen[k] = true
			if i > 0 && utf8.RuneCountInString(q) > 300 {
				t.Fatalf("oversized sub-query (%d runes)", utf8.RuneCountInString(q))
			}
		}
		if q := cleanGeneratedWebQuery(raw, "FALLBACK"); q != "FALLBACK" && (q == "" || utf8.RuneCountInString(q) > 300) {
			t.Fatalf("cleanGeneratedWebQuery = %q", q)
		}
		facts := parseMemoryFacts(raw)
		if len(facts) > 8 {
			t.Fatalf("%d memory facts", len(facts))
		}
		for _, fact := range facts {
			if fact == "" || strings.EqualFold(fact, "NONE") || utf8.RuneCountInString(fact) > 200 {
				t.Fatalf("bad memory fact %q", fact)
			}
		}
		plan := parseSearchPlan(raw, question, max, "TR", "auto")
		if len(plan.Queries) > max {
			t.Fatalf("search plan has %d queries > %d", len(plan.Queries), max)
		}
	})
}
