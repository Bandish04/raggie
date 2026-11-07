// SPDX-License-Identifier: Apache-2.0

package websearch

import (
	"context"
	"encoding/json"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/alicangunduz/raggie/services/edge/internal/ports"
)

func TestResearchRoundRobinsQueriesForCoverage(t *testing.T) {
	search := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		query := r.URL.Query().Get("q")
		if query == "q1" {
			time.Sleep(20 * time.Millisecond) // complete after q2 on purpose
		}
		results := map[string][]map[string]any{
			"q1": {
				{"title": "A1", "url": "https://a.example/1", "description": "a1"},
				{"title": "A2", "url": "https://a.example/2", "description": "a2"},
				{"title": "A3", "url": "https://a.example/3", "description": "a3"},
			},
			"q2": {
				{"title": "B1", "url": "https://b.example/1", "description": "b1"},
				{"title": "B2", "url": "https://b.example/2", "description": "b2"},
			},
		}
		_ = json.NewEncoder(w).Encode(map[string]any{
			"web": map[string]any{"results": results[query]},
		})
	}))
	defer search.Close()

	c := New("key", 4, 10)
	c.baseURL = search.URL
	rs, err := c.Research(context.Background(), "coverage", []string{"q1", "q2"}, ports.WebResearchOptions{
		TopN: 10, MaxResults: 4, QueryConcurrency: 2, ReadEnabled: false,
	})
	if err != nil {
		t.Fatal(err)
	}
	got := make([]string, len(rs))
	for i, result := range rs {
		got[i] = result.Title
	}
	want := []string{"A1", "B1", "A2", "B2"}
	if strings.Join(got, ",") != strings.Join(want, ",") {
		t.Fatalf("round-robin evidence = %v, want %v", got, want)
	}
}

func TestResearchBoundsQueryConcurrency(t *testing.T) {
	var active atomic.Int32
	var peak atomic.Int32
	search := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		current := active.Add(1)
		for {
			old := peak.Load()
			if current <= old || peak.CompareAndSwap(old, current) {
				break
			}
		}
		time.Sleep(25 * time.Millisecond)
		active.Add(-1)
		_ = json.NewEncoder(w).Encode(map[string]any{
			"web": map[string]any{"results": []map[string]any{
				{"title": r.URL.Query().Get("q"), "url": "https://" + r.URL.Query().Get("q") + ".example/1"},
			}},
		})
	}))
	defer search.Close()

	c := New("key", 8, 10)
	c.baseURL = search.URL
	_, err := c.Research(context.Background(), "bounded", []string{"q1", "q2", "q3", "q4"}, ports.WebResearchOptions{
		TopN: 10, MaxResults: 10, QueryConcurrency: 2, ReadEnabled: false,
	})
	if err != nil {
		t.Fatal(err)
	}
	if got := peak.Load(); got != 2 {
		t.Fatalf("peak query concurrency = %d, want 2", got)
	}
}

func TestSearchWithOptionsParamsAndDedupe(t *testing.T) {
	var gotQuery string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotQuery = r.URL.RawQuery
		if token := r.Header.Get("X-Subscription-Token"); token != "key" {
			t.Fatalf("missing subscription token: %q", token)
		}
		_ = json.NewEncoder(w).Encode(map[string]any{
			"query": map[string]any{"more_results_available": true},
			"web": map[string]any{"results": []map[string]any{
				{"title": "A", "url": "https://Example.com:443/path?utm_source=x&a=1#frag", "description": "one", "extra_snippets": []string{"extra"}},
				{"title": "A dup", "url": "https://example.com/path?a=1", "description": "dup"},
			}},
		})
	}))
	defer srv.Close()

	c := New("key", 1, 10)
	c.baseURL = srv.URL
	rs, more, err := c.SearchWithOptions(context.Background(), "raggie search", ports.WebSearchOptions{
		TopN: 99, Offset: 20, Freshness: "pw", Country: "tr", SearchLang: "tr", UILang: "tr-TR", ExtraSnippets: true,
	})
	if err != nil {
		t.Fatalf("SearchWithOptions: %v", err)
	}
	if !more {
		t.Fatalf("expected more_results_available=true")
	}
	for _, want := range []string{"count=20", "offset=20", "freshness=pw", "country=TR", "search_lang=tr", "ui_lang=tr-tr", "extra_snippets=true", "result_filter=web"} {
		if !strings.Contains(gotQuery, want) {
			t.Fatalf("query %q missing %q", gotQuery, want)
		}
	}
	if len(rs) != 1 {
		t.Fatalf("expected canonical dedupe to keep 1 result, got %d: %+v", len(rs), rs)
	}
	if rs[0].URL != "https://example.com/path?a=1" || rs[0].Query != "raggie search" || rs[0].ReadStatus != "snippet_only" {
		t.Fatalf("unexpected result enrichment: %+v", rs[0])
	}
	if len(rs[0].ExtraSnippets) != 1 || rs[0].ExtraSnippets[0] != "extra" {
		t.Fatalf("extra snippets not preserved: %+v", rs[0].ExtraSnippets)
	}
}

func TestPublicIPGuardAndCanonicalURL(t *testing.T) {
	for _, ip := range []string{"127.0.0.1", "10.0.0.5", "172.20.1.1", "192.168.1.1", "169.254.169.254", "::1"} {
		if isPublicIP(net.ParseIP(ip)) {
			t.Fatalf("expected %s to be blocked", ip)
		}
	}
	if !isPublicIP(net.ParseIP("8.8.8.8")) {
		t.Fatalf("expected 8.8.8.8 to be public")
	}
	got := CanonicalURL("https://Example.com:443/a?utm_campaign=x&b=2&fbclid=y#z")
	if got != "https://example.com/a?b=2" {
		t.Fatalf("unexpected canonical URL: %q", got)
	}
}

func TestResearchReadsPublicPageExcerpt(t *testing.T) {
	page := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html")
		_, _ = w.Write([]byte(`<html><head><title>Page Title</title><script>bad()</script></head><body><h1>Raggie</h1><p>Deep search reads public page content and extracts useful evidence.</p></body></html>`))
	}))
	defer page.Close()
	search := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(map[string]any{
			"web": map[string]any{"results": []map[string]any{
				{"title": "", "url": page.URL, "description": "snippet"},
			}},
		})
	}))
	defer search.Close()

	c := New("key", 1, 10)
	c.baseURL = search.URL
	c.reader = page.Client()
	rs, err := c.Research(context.Background(), "public page content", []string{"raggie"}, ports.WebResearchOptions{
		TopN: 5, MaxResults: 5, ReadEnabled: true, ReadTopN: 1, FetchConcurrency: 1,
	})
	if err != nil {
		t.Fatalf("Research: %v", err)
	}
	if len(rs) != 1 {
		t.Fatalf("expected 1 result, got %d", len(rs))
	}
	if rs[0].ReadStatus != "ok" || !strings.Contains(rs[0].Excerpt, "Deep search reads public page content") {
		t.Fatalf("page was not read into excerpt: %+v", rs[0])
	}
	if rs[0].Title != "Page Title" {
		t.Fatalf("expected HTML title fallback, got %q", rs[0].Title)
	}
}

func TestResearchCapsResultsPerHost(t *testing.T) {
	search := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(map[string]any{
			"web": map[string]any{"results": []map[string]any{
				{"title": "same 1", "url": "https://same.example/a", "description": "one"},
				{"title": "same 2", "url": "https://same.example/b", "description": "two"},
				{"title": "same 3", "url": "https://same.example/c", "description": "three"},
				{"title": "same 4", "url": "https://same.example/d", "description": "four"},
				{"title": "other", "url": "https://other.example/a", "description": "five"},
			}},
		})
	}))
	defer search.Close()

	c := New("key", 1, 10)
	c.baseURL = search.URL
	rs, err := c.Research(context.Background(), "host diversity", []string{"raggie"}, ports.WebResearchOptions{
		TopN: 10, MaxResults: 10, ReadEnabled: false,
	})
	if err != nil {
		t.Fatalf("Research: %v", err)
	}
	if len(rs) != 4 {
		t.Fatalf("expected 4 results after per-host cap, got %d: %+v", len(rs), rs)
	}
	for _, r := range rs {
		if r.URL == "https://same.example/d" {
			t.Fatalf("expected fourth same-host result to be skipped: %+v", rs)
		}
	}
}

func TestResearchReturnsErrorWhenEverySearchFails(t *testing.T) {
	search := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		http.Error(w, "invalid subscription token", http.StatusUnprocessableEntity)
	}))
	defer search.Close()

	c := New("invalid-key", 2, 10)
	c.baseURL = search.URL
	_, err := c.Research(context.Background(), "current policy rate", []string{"query one", "query two"}, ports.WebResearchOptions{
		TopN: 5, MaxResults: 10, QueryConcurrency: 2,
	})
	if err == nil || !strings.Contains(err.Error(), "unexpected status 422") {
		t.Fatalf("expected Brave status error, got %v", err)
	}
}

func TestResearchCachesReadPages(t *testing.T) {
	var pageHits int32
	page := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		atomic.AddInt32(&pageHits, 1)
		w.Header().Set("Content-Type", "text/html")
		_, _ = w.Write([]byte(`<html><head><title>Cached Page</title></head><body><p>Raggie cache keeps repeated public page reads from hitting the same URL twice.</p></body></html>`))
	}))
	defer page.Close()
	search := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(map[string]any{
			"web": map[string]any{"results": []map[string]any{
				{"title": "", "url": page.URL, "description": "snippet"},
			}},
		})
	}))
	defer search.Close()

	c := New("key", 1, 10)
	c.baseURL = search.URL
	c.reader = page.Client()
	opts := ports.WebResearchOptions{TopN: 5, MaxResults: 5, ReadEnabled: true, ReadTopN: 1, FetchConcurrency: 1}
	for i := 0; i < 2; i++ {
		rs, err := c.Research(context.Background(), "public page cache", []string{"raggie"}, opts)
		if err != nil {
			t.Fatalf("Research run %d: %v", i+1, err)
		}
		if len(rs) != 1 || rs[0].ReadStatus != "ok" || rs[0].Title != "Cached Page" {
			t.Fatalf("unexpected cached research result on run %d: %+v", i+1, rs)
		}
	}
	if got := atomic.LoadInt32(&pageHits); got != 1 {
		t.Fatalf("expected cached page to be fetched once, got %d fetches", got)
	}
}

func TestMakeExcerptRanksRelevantPassages(t *testing.T) {
	text := strings.Repeat("Introductory compliance boilerplate has generic background and no direct answer. ", 20) +
		"The useful passage explains that Raggie reranker scores evidence excerpts against the user question. " +
		"The evidence orchestration then keeps cited page passages for synthesis. " +
		"These details are the answer. " +
		strings.Repeat("Trailing legal boilerplate stays unrelated to the requested implementation. ", 20)

	excerpt := makeExcerpt(text, "How does the Raggie reranker choose evidence excerpts?", 320)
	if !strings.Contains(excerpt, "reranker scores evidence excerpts") {
		t.Fatalf("expected relevant passage in excerpt, got %q", excerpt)
	}
	if strings.HasPrefix(excerpt, "Introductory compliance boilerplate") {
		t.Fatalf("expected excerpt to start near relevant passage, got %q", excerpt)
	}
	if len([]rune(excerpt)) > 320 {
		t.Fatalf("excerpt exceeded limit: %d runes", len([]rune(excerpt)))
	}
}

// IPv6 transition/translation ranges embed (or route to) arbitrary IPv4
// addresses, so they must be blocked wholesale or an attacker can reach
// internal hosts through e.g. 64:ff9b::a9fe:a9fe (NAT64 of 169.254.169.254).
func TestPublicIPGuardBlocksIPv6TransitionRanges(t *testing.T) {
	for _, ip := range []string{
		"64:ff9b::a9fe:a9fe",     // NAT64 well-known prefix -> 169.254.169.254
		"64:ff9b::7f00:1",        // NAT64 -> 127.0.0.1
		"64:ff9b:1::a00:5",       // local-use NAT64 (RFC 8215)
		"2002:7f00:1::1",         // 6to4 embedding 127.0.0.1
		"2002:808:808::1",        // 6to4 (even "public" embeddings are blocked)
		"2001:0:4136:e378::1",    // Teredo
		"::ffff:127.0.0.1",       // IPv4-mapped loopback
		"::ffff:169.254.169.254", // IPv4-mapped metadata
		"::ffff:10.1.2.3",        // IPv4-mapped private
		"::127.0.0.1",            // deprecated IPv4-compatible
		"::a9fe:a9fe",            // deprecated IPv4-compatible metadata
		"100::1",                 // discard-only
		"fd00:ec2::254",          // AWS IMDS IPv6 (ULA)
	} {
		if isPublicIP(net.ParseIP(ip)) {
			t.Errorf("expected %s to be blocked", ip)
		}
	}
	for _, ip := range []string{"2606:4700:4700::1111", "2a00:1450:4001:82a::200e", "::ffff:8.8.8.8"} {
		if !isPublicIP(net.ParseIP(ip)) {
			t.Errorf("expected %s to be allowed", ip)
		}
	}
}

// Transport errors from net/http embed the full request URL (with ?q=<user
// query>); callers log these errors, so the URL must be stripped.
func TestSearchTransportErrorOmitsQuery(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {}))
	base := srv.URL
	srv.Close() // connection refused from here on

	c := New("key", 1, 5)
	c.baseURL = base
	_, err := c.Search(context.Background(), "ayse yilmaz 12345678901", 5)
	if err == nil {
		t.Fatal("expected a transport error")
	}
	if strings.Contains(err.Error(), "12345678901") || strings.Contains(err.Error(), "yilmaz") {
		t.Fatalf("error leaks the query: %v", err)
	}
}

// The page reader New wires refuses private targets when it dials, whatever
// the URL looks like: an IP literal, or a public-looking name that resolves to
// a private address (DNS rebinding). The listener must never see a request.
func TestPageReaderRefusesPrivateTargetsAtDialTime(t *testing.T) {
	var hits atomic.Int32
	page := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		hits.Add(1)
		_, _ = w.Write([]byte("internal"))
	}))
	defer page.Close()
	_, port, _ := net.SplitHostPort(strings.TrimPrefix(page.URL, "http://"))

	orig := lookupIPAddr
	t.Cleanup(func() { lookupIPAddr = orig })
	lookupIPAddr = func(_ context.Context, host string) ([]net.IPAddr, error) {
		if host == "rebind.example" {
			return []net.IPAddr{{IP: net.ParseIP("127.0.0.1")}}, nil
		}
		return orig(context.Background(), host)
	}

	reader := New("key", 1, 10).reader
	for _, target := range []string{page.URL, "http://rebind.example:" + port + "/"} {
		resp, err := reader.Get(target)
		if err == nil {
			_ = resp.Body.Close()
			t.Fatalf("%s: private target was fetched (status %d)", target, resp.StatusCode)
		}
		if !strings.Contains(err.Error(), "blocked private") {
			t.Fatalf("%s: expected a dial-time block, got %v", target, err)
		}
	}
	if n := hits.Load(); n != 0 {
		t.Fatalf("the private listener received %d request(s)", n)
	}
}
