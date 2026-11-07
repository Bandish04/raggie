// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"strconv"
	"strings"
	"testing"

	"github.com/alicangunduz/raggie/services/edge/internal/config"
	"github.com/alicangunduz/raggie/services/edge/internal/ports"
	"github.com/alicangunduz/raggie/services/edge/internal/ports/mock"
)

func TestDeepResearchOptionsSeparateQueryAndPageConcurrency(t *testing.T) {
	opts := webResearchOptions(config.Config{
		DeepSearchTopN:            10,
		DeepSearchMaxResults:      50,
		DeepSearchParallelism:     2,
		WebSearchFetchConcurrency: 7,
	}, true)
	if opts.QueryConcurrency != 2 {
		t.Fatalf("query concurrency = %d, want 2", opts.QueryConcurrency)
	}
	if opts.FetchConcurrency != 7 {
		t.Fatalf("page fetch concurrency = %d, want 7", opts.FetchConcurrency)
	}
}

func discardLogger() *slog.Logger { return slog.New(slog.NewTextHandler(io.Discard, nil)) }

// parseSubQueries always puts the original question first, strips bullets/quotes,
// drops empties + dupes (case-insensitive), and caps the total at maxQueries.
func TestParseSubQueries(t *testing.T) {
	raw := "1. izin politikası nedir\n- yıllık izin süresi\n\"izin politikası nedir\"\nremote çalışma kuralları\nfazla mesai hakları"
	got := parseSubQueries(raw, "şirket izin politikası", 4)

	if len(got) != 4 {
		t.Fatalf("expected cap of 4 queries, got %d: %v", len(got), got)
	}
	if got[0] != "şirket izin politikası" {
		t.Fatalf("original question must be first, got %q", got[0])
	}
	for _, q := range got {
		if strings.HasPrefix(q, "-") || strings.HasPrefix(q, "1.") || strings.Contains(q, "\"") {
			t.Fatalf("query not cleaned of bullets/numbering/quotes: %q", q)
		}
	}
	// "izin politikası nedir" appears with numbering and again quoted -> one entry.
	seen := map[string]int{}
	for _, q := range got {
		seen[strings.ToLower(q)]++
	}
	for q, n := range seen {
		if n > 1 {
			t.Fatalf("duplicate query %q appeared %d times", q, n)
		}
	}
}

// An empty/garbage generation still yields the original question (graceful).
func TestParseSubQueriesFallsBackToQuestion(t *testing.T) {
	got := parseSubQueries("\n  \n- \n", "tek soru", 4)
	if len(got) != 1 || got[0] != "tek soru" {
		t.Fatalf("expected just the original question, got %v", got)
	}
}

func TestCleanGeneratedWebQueryAcceptsPlainTextAndJSON(t *testing.T) {
	tests := []struct {
		name string
		raw  string
		want string
	}{
		{name: "plain", raw: `"TCMB politika faizi Haziran 2026"`, want: "TCMB politika faizi Haziran 2026"},
		{name: "query object", raw: `{"query":"TCMB politika faizi resmi kaynak"}`, want: "TCMB politika faizi resmi kaynak"},
		{name: "queries object", raw: `{"queries":["Qdrant latest stable release","fallback"]}`, want: "Qdrant latest stable release"},
		{name: "fenced object", raw: "```json\n{\"query\":\"EU AI Act 2026 obligations\"}\n```", want: "EU AI Act 2026 obligations"},
		{name: "malformed suffix", raw: `"TCMB politika faizi resmi kaynak"}`, want: "TCMB politika faizi resmi kaynak"},
		{name: "malformed label", raw: `{"query": "Kubernetes supported versions"}`, want: "Kubernetes supported versions"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := cleanGeneratedWebQuery(tt.raw, "fallback"); got != tt.want {
				t.Fatalf("cleanGeneratedWebQuery(%q) = %q, want %q", tt.raw, got, tt.want)
			}
		})
	}
}

// generateSubQueries drains the (canned) gen stream and returns a cleaned list
// that always contains the original question. The mock returns its Response for
// the gen call (one query per line).
func TestGenerateSubQueries(t *testing.T) {
	deps := Deps{Chat: mock.ChatProvider{Response: "alpha\nbeta\ngamma"}}
	// The mock streams word-by-word with trailing spaces; parsing trims them.
	got := generateSubQueries(
		context.Background(),
		deps,
		discardLogger(),
		"",
		"orijinal soru",
		4,
	)
	if got[0] != "orijinal soru" {
		t.Fatalf("original question must be first, got %v", got)
	}
	if len(got) < 2 {
		t.Fatalf("expected the original question plus generated queries, got %v", got)
	}
}

// deepSearch searches each query SEQUENTIALLY (recorded in order), dedupes by URL,
// and preserves discovery order (so the [n] context labels match the sources cards).
func TestDeepSearchDedupesAndOrders(t *testing.T) {
	web := &mock.WebSearcher{
		Results: map[string][]ports.WebResult{
			"q1": {{Title: "A", URL: "http://a", Snippet: "sa"}, {Title: "B", URL: "http://b", Snippet: "sb"}},
			"q2": {{Title: "B-dup", URL: "http://b", Snippet: "dup"}, {Title: "C", URL: "http://c", Snippet: "sc"}},
		},
	}
	deps := Deps{Web: web}
	got := deepSearch(context.Background(), deps, discardLogger(), []string{"q1", "q2"}, 5, 50)

	urls := make([]string, len(got))
	for i, r := range got {
		urls[i] = r.URL
	}
	want := []string{"http://a", "http://b", "http://c"}
	if strings.Join(urls, ",") != strings.Join(want, ",") {
		t.Fatalf("expected deduped discovery order %v, got %v", want, urls)
	}
	if q := web.AskedQueries(); len(q) != 2 || q[0] != "q1" || q[1] != "q2" {
		t.Fatalf("expected sequential q1 then q2, got %v", q)
	}
}

// A per-query error is non-fatal: deepSearch logs it and continues with the rest.
func TestDeepSearchPerQueryErrorIsNonFatal(t *testing.T) {
	web := &mock.WebSearcher{
		Results: map[string][]ports.WebResult{
			// q1 has no entry and no Default -> empty (the "this query found nothing"
			// case); q2 returns a hit. Neither aborts the loop.
			"q2": {{Title: "C", URL: "http://c", Snippet: "sc"}},
		},
	}
	deps := Deps{Web: web}
	got := deepSearch(context.Background(), deps, discardLogger(), []string{"q1", "q2"}, 5, 50)
	if len(got) != 1 || got[0].URL != "http://c" {
		t.Fatalf("expected to skip empty q1 and keep q2's hit, got %v", got)
	}

	// A hard error on every call yields zero results (caller then falls back).
	errWeb := &mock.WebSearcher{Err: errors.New("brave down")}
	got = deepSearch(context.Background(), Deps{Web: errWeb}, discardLogger(), []string{"q1", "q2"}, 5, 50)
	if len(got) != 0 {
		t.Fatalf("expected zero results when every search errors, got %v", got)
	}
}

// deepSearch caps the deduped total at the maxResults arg (cfg.DeepSearchMaxResults)
// across all queries.
func TestDeepSearchCapsTotal(t *testing.T) {
	const maxResults = 50
	many := make([]ports.WebResult, 0, maxResults+10)
	for i := 0; i < maxResults+10; i++ {
		many = append(many, ports.WebResult{URL: "http://x/" + strconv.Itoa(i)})
	}
	web := &mock.WebSearcher{Default: many}
	got := deepSearch(context.Background(), Deps{Web: web}, discardLogger(), []string{"only"}, 100, maxResults)
	if len(got) != maxResults {
		t.Fatalf("expected total capped at %d, got %d", maxResults, len(got))
	}
}

// webContextBlock labels results [1..N] in slice order so the [n] citations line
// up with the SSE sources cards (which iterate the same slice).
func TestWebContextBlockLabelsInOrder(t *testing.T) {
	block := webContextBlock([]ports.WebResult{
		{Title: "First", URL: "http://1", Snippet: "s1"},
		{Title: "", URL: "http://2", Snippet: "s2"}, // no title -> URL used as label
	})
	if !strings.Contains(block, "[1] (source: First — http://1)") {
		t.Fatalf("missing labeled [1] entry: %q", block)
	}
	if !strings.Contains(block, "[2] (source: http://2 — http://2)") {
		t.Fatalf("title-less result should fall back to URL: %q", block)
	}
	if strings.Index(block, "[1]") > strings.Index(block, "[2]") {
		t.Fatalf("labels out of order: %q", block)
	}
}
