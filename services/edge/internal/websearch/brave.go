// SPDX-License-Identifier: Apache-2.0

// Package websearch implements the optional web-search fallback used when the
// user's documents don't answer a question. The Brave client is fail-open and
// concurrency-bounded: any error (or a saturated pool) leaves the caller on the
// documents-only path so the chat never blocks on web search.
package websearch

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"mime"
	"net"
	"net/http"
	"net/netip"
	"net/url"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"golang.org/x/net/html"

	"github.com/alicangunduz/raggie/services/edge/internal/outboundhttp"
	"github.com/alicangunduz/raggie/services/edge/internal/ports"
)

const (
	maxBraveCount        = 20
	defaultReadTopN      = 8
	defaultFetchTimeoSec = 5
	defaultMaxBodyBytes  = int64(1_500_000)
	defaultExcerptRunes  = 2800
	maxResultsPerHost    = 3
	pageCacheTTL         = 30 * time.Minute
)

// ErrBusy is returned when the bounded outbound pool is at capacity; the caller
// falls back to the documents-only answer.
var ErrBusy = errors.New("web search pool at capacity")

// Client is a Brave Web Search API client implementing ports.WebSearcher and,
// when the richer path is wired, ports.WebResearcher.
type Client struct {
	apiKey  string
	topN    int
	baseURL string
	http    *http.Client
	reader  *http.Client
	sem     chan struct{} // counting semaphore: bounds concurrent Brave calls
	cacheMu sync.Mutex
	cache   map[string]cachedPage
}

type cachedPage struct {
	title     string
	excerpt   string
	status    string
	expiresAt time.Time
}

// New builds a Brave client. topN is the default result count; maxConcurrency
// bounds in-flight search requests (mirrors the LLM pool ceiling).
func New(apiKey string, maxConcurrency, topN int) *Client {
	if maxConcurrency <= 0 {
		maxConcurrency = 1
	}
	if topN <= 0 {
		topN = 10
	}
	return &Client{
		apiKey:  apiKey,
		topN:    topN,
		baseURL: "https://api.search.brave.com/res/v1/web/search",
		http:    outboundhttp.NewClient(8 * time.Second),
		reader:  publicHTTPClient(),
		sem:     make(chan struct{}, maxConcurrency),
		cache:   make(map[string]cachedPage),
	}
}

type braveResponse struct {
	Query struct {
		MoreResultsAvailable bool `json:"more_results_available"`
	} `json:"query"`
	Web struct {
		Results []struct {
			Title         string   `json:"title"`
			URL           string   `json:"url"`
			Description   string   `json:"description"`
			ExtraSnippets []string `json:"extra_snippets"`
		} `json:"results"`
	} `json:"web"`
}

// Search queries Brave and returns up to topN results. It is the compatibility
// method for older callers; richer callers should use SearchWithOptions.
func (c *Client) Search(ctx context.Context, query string, topN int) ([]ports.WebResult, error) {
	rs, _, err := c.SearchWithOptions(ctx, query, ports.WebSearchOptions{
		TopN:          topN,
		ResultFilter:  "web",
		ExtraSnippets: true,
	})
	return rs, err
}

// SearchWithOptions performs one Brave Web Search request with explicit knobs.
// The returned bool mirrors Brave's query.more_results_available.
func (c *Client) SearchWithOptions(ctx context.Context, query string, opts ports.WebSearchOptions) ([]ports.WebResult, bool, error) {
	if opts.TopN <= 0 {
		opts.TopN = c.topN
	}
	if opts.TopN > maxBraveCount {
		opts.TopN = maxBraveCount
	}
	select {
	case c.sem <- struct{}{}:
		defer func() { <-c.sem }()
	default:
		return nil, false, ErrBusy
	}

	q := url.Values{}
	q.Set("q", query)
	q.Set("count", strconv.Itoa(opts.TopN))
	if opts.Offset > 0 {
		q.Set("offset", strconv.Itoa(opts.Offset))
	}
	if opts.Freshness != "" {
		q.Set("freshness", opts.Freshness)
	}
	if opts.Country != "" {
		q.Set("country", strings.ToUpper(opts.Country))
	}
	if lang := normalizedLang(opts.SearchLang); lang != "" {
		q.Set("search_lang", lang)
	}
	if lang := normalizedLang(opts.UILang); lang != "" {
		q.Set("ui_lang", lang)
	}
	resultFilter := opts.ResultFilter
	if resultFilter == "" {
		resultFilter = "web"
	}
	q.Set("result_filter", resultFilter)
	if opts.ExtraSnippets {
		q.Set("extra_snippets", "true")
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodGet,
		c.baseURL+"?"+q.Encode(), nil)
	if err != nil {
		return nil, false, err
	}
	req.Header.Set("Accept", "application/json")
	req.Header.Set("X-Subscription-Token", c.apiKey)

	resp, err := c.http.Do(req)
	if err != nil {
		return nil, false, redactURLError(err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, false, fmt.Errorf("brave: unexpected status %d", resp.StatusCode)
	}

	var body braveResponse
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		return nil, false, err
	}
	now := time.Now().UTC().Format(time.RFC3339)
	out := make([]ports.WebResult, 0, len(body.Web.Results))
	seen := map[string]bool{}
	for _, r := range body.Web.Results {
		canon := CanonicalURL(r.URL)
		if canon == "" || seen[canon] {
			continue
		}
		seen[canon] = true
		out = append(out, ports.WebResult{
			Title:         strings.TrimSpace(r.Title),
			URL:           canon,
			Snippet:       strings.TrimSpace(r.Description),
			ExtraSnippets: cleanSnippets(r.ExtraSnippets),
			Query:         query,
			RetrievedAt:   now,
			ReadStatus:    "snippet_only",
		})
	}
	return out, body.Query.MoreResultsAvailable, nil
}

// Research gathers SERP results for multiple queries, dedupes them by canonical
// URL, optionally reads public page bodies, and returns enriched evidence.
func (c *Client) Research(ctx context.Context, question string, queries []string, opts ports.WebResearchOptions) ([]ports.WebResult, error) {
	if len(queries) == 0 {
		queries = []string{question}
	}
	opts = normalizeResearchOptions(opts, c.topN)
	if opts.TotalTimeoutSecs > 0 {
		var cancel context.CancelFunc
		ctx, cancel = context.WithTimeout(ctx, time.Duration(opts.TotalTimeoutSecs)*time.Second)
		defer cancel()
	}

	collected := make([]ports.WebResult, 0, opts.MaxResults)
	seen := map[string]bool{}
	hostCounts := map[string]int{}
	perQuery, err := c.searchQueries(ctx, queries, opts)
	if err != nil {
		return nil, err
	}

	// Merge breadth-first across queries. This keeps deterministic plan order
	// while ensuring the first query cannot consume the whole evidence budget.
	for rank := 0; len(collected) < opts.MaxResults; rank++ {
		sawCandidate := false
		for queryIndex := range perQuery {
			if rank >= len(perQuery[queryIndex]) {
				continue
			}
			sawCandidate = true
			r := perQuery[queryIndex][rank]
			if r.URL == "" || seen[r.URL] {
				continue
			}
			host := hostOf(r.URL)
			if host != "" && hostCounts[host] >= maxResultsPerHost {
				continue
			}
			seen[r.URL] = true
			if host != "" {
				hostCounts[host]++
			}
			collected = append(collected, r)
			if len(collected) >= opts.MaxResults {
				break
			}
		}
		if !sawCandidate {
			break
		}
	}
	if len(collected) == 0 || !opts.ReadEnabled {
		return collected, nil
	}

	readN := opts.ReadTopN
	if readN <= 0 || readN > len(collected) {
		readN = len(collected)
	}
	if readN > 0 {
		c.readPages(ctx, question, collected[:readN], opts)
	}
	return collected, nil
}

func (c *Client) searchQueries(
	ctx context.Context,
	queries []string,
	opts ports.WebResearchOptions,
) ([][]ports.WebResult, error) {
	results := make([][]ports.WebResult, len(queries))
	workers := opts.QueryConcurrency
	if workers > len(queries) {
		workers = len(queries)
	}
	if workers <= 0 {
		return results, nil
	}

	jobs := make(chan int)
	var wg sync.WaitGroup
	var errorMu sync.Mutex
	var firstError error
	successfulQueries := 0
	for i := 0; i < workers; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for idx := range jobs {
				if ctx.Err() != nil {
					return
				}
				rs, _, err := c.SearchWithOptions(ctx, queries[idx], ports.WebSearchOptions{
					TopN:          opts.TopN,
					Country:       opts.Country,
					SearchLang:    opts.SearchLang,
					UILang:        opts.UILang,
					Freshness:     opts.Freshness,
					ResultFilter:  opts.ResultFilter,
					ExtraSnippets: opts.ExtraSnippets,
				})
				errorMu.Lock()
				if err != nil {
					if firstError == nil {
						firstError = err
					}
				} else {
					successfulQueries++
					results[idx] = rs
				}
				errorMu.Unlock()
			}
		}()
	}
sendLoop:
	for i := range queries {
		select {
		case <-ctx.Done():
			break sendLoop
		case jobs <- i:
		}
	}
	close(jobs)
	wg.Wait()
	if successfulQueries == 0 && firstError != nil {
		return results, firstError
	}
	return results, nil
}

func normalizeResearchOptions(opts ports.WebResearchOptions, defaultTopN int) ports.WebResearchOptions {
	if opts.TopN <= 0 {
		opts.TopN = defaultTopN
	}
	if opts.TopN > maxBraveCount {
		opts.TopN = maxBraveCount
	}
	if opts.MaxResults <= 0 {
		opts.MaxResults = opts.TopN
	}
	if opts.ReadTopN <= 0 {
		opts.ReadTopN = defaultReadTopN
	}
	if opts.QueryConcurrency <= 0 {
		opts.QueryConcurrency = 1
	}
	if opts.FetchConcurrency <= 0 {
		opts.FetchConcurrency = 4
	}
	if opts.FetchTimeout <= 0 {
		opts.FetchTimeout = defaultFetchTimeoSec
	}
	if opts.MaxBodyBytes <= 0 {
		opts.MaxBodyBytes = defaultMaxBodyBytes
	}
	if opts.ResultFilter == "" {
		opts.ResultFilter = "web"
	}
	return opts
}

func (c *Client) readPages(ctx context.Context, question string, results []ports.WebResult, opts ports.WebResearchOptions) {
	workers := opts.FetchConcurrency
	if workers > len(results) {
		workers = len(results)
	}
	jobs := make(chan int)
	var wg sync.WaitGroup
	for i := 0; i < workers; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for idx := range jobs {
				if ctx.Err() != nil {
					return
				}
				title, excerpt, status := c.readOne(ctx, question, results[idx].URL, opts)
				if title != "" && results[idx].Title == "" {
					results[idx].Title = title
				}
				results[idx].Excerpt = excerpt
				results[idx].ReadStatus = status
			}
		}()
	}
sendLoop:
	for i := range results {
		select {
		case <-ctx.Done():
			break sendLoop
		case jobs <- i:
		}
	}
	close(jobs)
	wg.Wait()
}

func (c *Client) readOne(ctx context.Context, question, rawURL string, opts ports.WebResearchOptions) (title, excerpt, status string) {
	u, err := url.Parse(rawURL)
	if err != nil || !isAllowedScheme(u.Scheme) || u.Hostname() == "" {
		return "", "", "blocked_url"
	}
	if cached, ok := c.cachedPage(rawURL); ok {
		return cached.title, cached.excerpt, cached.status
	}
	rctx, cancel := context.WithTimeout(ctx, time.Duration(opts.FetchTimeout)*time.Second)
	defer cancel()
	req, err := http.NewRequestWithContext(rctx, http.MethodGet, rawURL, nil)
	if err != nil {
		return "", "", "fetch_error"
	}
	req.Header.Set("User-Agent", "RaggieBot/1.0 (+https://raggie.local)")
	req.Header.Set("Accept", "text/html,text/plain;q=0.9,*/*;q=0.1")
	resp, err := c.reader.Do(req)
	if err != nil {
		return "", "", "fetch_error"
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return "", "", fmt.Sprintf("http_%d", resp.StatusCode)
	}
	mediaType, _, _ := mime.ParseMediaType(resp.Header.Get("Content-Type"))
	mediaType = strings.ToLower(mediaType)
	if mediaType != "" && mediaType != "text/html" && mediaType != "text/plain" && mediaType != "application/xhtml+xml" {
		return "", "", "unsupported_content"
	}
	limited := io.LimitReader(resp.Body, opts.MaxBodyBytes+1)
	raw, err := io.ReadAll(limited)
	if err != nil {
		return "", "", "fetch_error"
	}
	if int64(len(raw)) > opts.MaxBodyBytes {
		return "", "", "too_large"
	}
	var text string
	if mediaType == "text/plain" {
		text = normalizeSpace(string(raw))
	} else {
		title, text = extractHTML(raw)
	}
	if strings.TrimSpace(text) == "" {
		return title, "", "empty"
	}
	excerpt = makeExcerpt(text, question, defaultExcerptRunes)
	c.storeCachedPage(rawURL, cachedPage{title: title, excerpt: excerpt, status: "ok", expiresAt: time.Now().Add(pageCacheTTL)})
	return title, excerpt, "ok"
}

func (c *Client) cachedPage(rawURL string) (cachedPage, bool) {
	c.cacheMu.Lock()
	defer c.cacheMu.Unlock()
	p, ok := c.cache[rawURL]
	if !ok || time.Now().After(p.expiresAt) {
		if ok {
			delete(c.cache, rawURL)
		}
		return cachedPage{}, false
	}
	return p, true
}

func (c *Client) storeCachedPage(rawURL string, page cachedPage) {
	c.cacheMu.Lock()
	defer c.cacheMu.Unlock()
	if len(c.cache) > 512 {
		for k, v := range c.cache {
			if time.Now().After(v.expiresAt) {
				delete(c.cache, k)
			}
		}
	}
	c.cache[rawURL] = page
}

func publicHTTPClient() *http.Client {
	return &http.Client{
		Timeout: 0,
		Transport: &http.Transport{
			Proxy:                 nil,
			DialContext:           publicDialContext,
			TLSHandshakeTimeout:   5 * time.Second,
			ResponseHeaderTimeout: 5 * time.Second,
			IdleConnTimeout:       30 * time.Second,
			MaxIdleConns:          64,
			MaxIdleConnsPerHost:   4,
		},
		CheckRedirect: func(req *http.Request, via []*http.Request) error {
			if len(via) >= 3 {
				return errors.New("too many redirects")
			}
			if !isAllowedScheme(req.URL.Scheme) {
				return errors.New("blocked redirect scheme")
			}
			return nil
		},
	}
}

// lookupIPAddr resolves page hosts for publicDialContext (a test hook).
var lookupIPAddr = net.DefaultResolver.LookupIPAddr

func publicDialContext(ctx context.Context, network, address string) (net.Conn, error) {
	host, port, err := net.SplitHostPort(address)
	if err != nil {
		return nil, err
	}
	if strings.EqualFold(host, "localhost") {
		return nil, errors.New("blocked private host")
	}
	ips, err := lookupIPAddr(ctx, host)
	if err != nil {
		return nil, err
	}
	for _, ip := range ips {
		if !isPublicIP(ip.IP) {
			continue
		}
		d := net.Dialer{Timeout: 5 * time.Second}
		return d.DialContext(ctx, network, net.JoinHostPort(ip.IP.String(), port))
	}
	return nil, errors.New("blocked private address")
}

// redactURLError drops the request URL from a net/http *url.Error: for the
// search API it carries ?q=<user query>, and these errors are logged.
func redactURLError(err error) error {
	var ue *url.Error
	if errors.As(err, &ue) {
		return fmt.Errorf("brave: %s request failed: %w", ue.Op, ue.Err)
	}
	return err
}

func isAllowedScheme(s string) bool {
	return s == "http" || s == "https"
}

var blockedCIDRs = []netip.Prefix{
	mustPrefix("0.0.0.0/8"),
	mustPrefix("10.0.0.0/8"),
	mustPrefix("100.64.0.0/10"),
	mustPrefix("127.0.0.0/8"),
	mustPrefix("169.254.0.0/16"),
	mustPrefix("172.16.0.0/12"),
	mustPrefix("192.0.0.0/24"),
	mustPrefix("192.0.2.0/24"),
	mustPrefix("192.168.0.0/16"),
	mustPrefix("198.18.0.0/15"),
	mustPrefix("198.51.100.0/24"),
	mustPrefix("203.0.113.0/24"),
	mustPrefix("224.0.0.0/4"),
	mustPrefix("240.0.0.0/4"),
	// IPv6. IPv4-mapped (::ffff:0:0/96) addresses are Unmap()ped and checked
	// against the IPv4 list above; the ranges below embed or translate to
	// arbitrary IPv4 destinations and are blocked wholesale.
	mustPrefix("::/96"),          // unspecified, loopback, deprecated IPv4-compatible
	mustPrefix("64:ff9b::/96"),   // NAT64 well-known prefix (RFC 6052)
	mustPrefix("64:ff9b:1::/48"), // local-use NAT64 (RFC 8215)
	mustPrefix("100::/64"),       // discard-only (RFC 6666)
	mustPrefix("2001::/32"),      // Teredo
	mustPrefix("2002::/16"),      // 6to4
	mustPrefix("fc00::/7"),
	mustPrefix("fe80::/10"),
	mustPrefix("ff00::/8"),
	mustPrefix("2001:db8::/32"),
}

func mustPrefix(s string) netip.Prefix {
	p, err := netip.ParsePrefix(s)
	if err != nil {
		panic(err)
	}
	return p
}

func isPublicIP(ip net.IP) bool {
	addr, ok := netip.AddrFromSlice(ip)
	if !ok {
		return false
	}
	addr = addr.Unmap()
	if !addr.IsGlobalUnicast() || addr.IsPrivate() || addr.IsLoopback() || addr.IsLinkLocalUnicast() ||
		addr.IsLinkLocalMulticast() || addr.IsMulticast() || addr.IsUnspecified() {
		return false
	}
	for _, p := range blockedCIDRs {
		if p.Contains(addr) {
			return false
		}
	}
	return true
}

// CanonicalURL normalizes URLs for dedupe and removes common tracking params.
func CanonicalURL(raw string) string {
	u, err := url.Parse(strings.TrimSpace(raw))
	if err != nil || !isAllowedScheme(u.Scheme) || u.Host == "" {
		return ""
	}
	u.Scheme = strings.ToLower(u.Scheme)
	host := strings.ToLower(strings.TrimRight(u.Hostname(), "."))
	if host == "" { // e.g. "http://." — no usable host left
		return ""
	}
	port := u.Port()
	if port != "" && !((u.Scheme == "http" && port == "80") || (u.Scheme == "https" && port == "443")) {
		host = net.JoinHostPort(host, port)
	}
	u.Host = host
	u.Fragment = ""
	q := u.Query()
	for key := range q {
		lk := strings.ToLower(key)
		if strings.HasPrefix(lk, "utm_") || lk == "fbclid" || lk == "gclid" || lk == "mc_cid" || lk == "mc_eid" ||
			lk == "igshid" || lk == "ref" || lk == "ref_src" {
			q.Del(key)
		}
	}
	u.RawQuery = q.Encode()
	return u.String()
}

func cleanSnippets(in []string) []string {
	out := make([]string, 0, len(in))
	seen := map[string]bool{}
	for _, s := range in {
		s = normalizeSpace(s)
		if s == "" || seen[s] {
			continue
		}
		seen[s] = true
		out = append(out, s)
	}
	return out
}

func normalizedLang(v string) string {
	v = strings.TrimSpace(strings.ToLower(v))
	if v == "" || v == "auto" {
		return ""
	}
	return v
}

func extractHTML(raw []byte) (title, text string) {
	root, err := html.Parse(strings.NewReader(string(raw)))
	if err != nil {
		return "", normalizeSpace(string(raw))
	}
	var parts []string
	var walk func(*html.Node, bool)
	walk = func(n *html.Node, skip bool) {
		if n.Type == html.ElementNode {
			name := strings.ToLower(n.Data)
			if name == "script" || name == "style" || name == "noscript" || name == "svg" || name == "canvas" ||
				name == "iframe" || name == "form" || name == "nav" || name == "footer" || name == "header" {
				skip = true
			}
			if name == "title" {
				title = normalizeSpace(nodeText(n))
			}
		}
		if !skip && n.Type == html.TextNode {
			if s := normalizeSpace(n.Data); s != "" {
				parts = append(parts, s)
			}
		}
		for child := n.FirstChild; child != nil; child = child.NextSibling {
			walk(child, skip)
		}
	}
	walk(root, false)
	return title, normalizeSpace(strings.Join(parts, " "))
}

func nodeText(n *html.Node) string {
	var b strings.Builder
	var walk func(*html.Node)
	walk = func(x *html.Node) {
		if x.Type == html.TextNode {
			b.WriteString(x.Data)
			b.WriteByte(' ')
		}
		for child := x.FirstChild; child != nil; child = child.NextSibling {
			walk(child)
		}
	}
	walk(n)
	return b.String()
}

var wsRE = regexp.MustCompile(`\s+`)

func normalizeSpace(s string) string {
	return strings.TrimSpace(wsRE.ReplaceAllString(s, " "))
}

func makeExcerpt(text, question string, maxRunes int) string {
	text = normalizeSpace(text)
	if maxRunes <= 0 {
		maxRunes = defaultExcerptRunes
	}
	runes := []rune(text)
	if len(runes) <= maxRunes {
		return text
	}
	terms := queryTerms(question)
	passages := rankPassages(splitPassages(text), terms)
	if len(passages) == 0 {
		return trimRunes(text, maxRunes)
	}
	var b strings.Builder
	used := 0
	sep := "\n...\n"
	sepLen := len([]rune(sep))
	for _, p := range passages {
		pr := []rune(p.text)
		if len(pr) == 0 {
			continue
		}
		available := maxRunes - used
		if used > 0 {
			if available <= sepLen+120 {
				break
			}
			b.WriteString("\n...\n")
			used += sepLen
			available -= sepLen
		}
		if len(pr) > available {
			if available <= 0 {
				break
			}
			if available > 3 {
				b.WriteString(string(pr[:available-3]))
				b.WriteString("...")
			} else {
				b.WriteString(string(pr[:available]))
			}
			used = maxRunes
			break
		}
		b.WriteString(p.text)
		used += len(pr)
		if used >= maxRunes {
			break
		}
	}
	if b.Len() == 0 {
		return trimRunes(text, maxRunes)
	}
	return b.String()
}

func trimRunes(s string, maxRunes int) string {
	runes := []rune(s)
	if maxRunes <= 0 || len(runes) <= maxRunes {
		return s
	}
	return string(runes[:maxRunes])
}

type scoredPassage struct {
	text  string
	score int
}

func splitPassages(text string) []string {
	sentences := splitSentences(text)
	out := make([]string, 0, len(sentences))
	for i := 0; i < len(sentences); i++ {
		var b strings.Builder
		for j := i; j < len(sentences) && j < i+3; j++ {
			if b.Len() > 0 {
				b.WriteByte(' ')
			}
			b.WriteString(sentences[j])
			if len([]rune(b.String())) >= 850 {
				break
			}
		}
		if s := strings.TrimSpace(b.String()); len([]rune(s)) >= 80 {
			out = append(out, s)
		}
	}
	if len(out) == 0 && strings.TrimSpace(text) != "" {
		out = []string{text}
	}
	return out
}

func splitSentences(text string) []string {
	var out []string
	start := 0
	runes := []rune(text)
	for i, r := range runes {
		if r != '.' && r != '!' && r != '?' && r != '。' && r != '؟' {
			continue
		}
		if i+1 < len(runes) && runes[i+1] != ' ' {
			continue
		}
		if s := strings.TrimSpace(string(runes[start : i+1])); s != "" {
			out = append(out, s)
		}
		start = i + 1
	}
	if start < len(runes) {
		if s := strings.TrimSpace(string(runes[start:])); s != "" {
			out = append(out, s)
		}
	}
	return out
}

func rankPassages(passages []string, terms []string) []scoredPassage {
	scored := make([]scoredPassage, 0, len(passages))
	for _, p := range passages {
		score := scorePassage(p, terms)
		if score > 0 {
			scored = append(scored, scoredPassage{text: p, score: score})
		}
	}
	sort.SliceStable(scored, func(i, j int) bool {
		if scored[i].score == scored[j].score {
			return len([]rune(scored[i].text)) < len([]rune(scored[j].text))
		}
		return scored[i].score > scored[j].score
	})
	if len(scored) > 3 {
		return scored[:3]
	}
	return scored
}

func scorePassage(p string, terms []string) int {
	lower := strings.ToLower(p)
	score := 0
	for i, term := range terms {
		count := strings.Count(lower, term)
		if count == 0 {
			continue
		}
		weight := 10
		if i < 3 {
			weight = 18
		}
		score += count * weight
	}
	return score
}

func queryTerms(q string) []string {
	fields := strings.Fields(strings.ToLower(q))
	terms := make([]string, 0, len(fields))
	for _, f := range fields {
		f = strings.Trim(f, ".,;:!?()[]{}\"'`")
		if len([]rune(f)) >= 4 {
			terms = append(terms, f)
		}
	}
	sort.SliceStable(terms, func(i, j int) bool { return len([]rune(terms[i])) > len([]rune(terms[j])) })
	if len(terms) > 8 {
		return terms[:8]
	}
	return terms
}

func hostOf(rawURL string) string {
	u, err := url.Parse(rawURL)
	if err != nil {
		return ""
	}
	return strings.ToLower(u.Hostname())
}

var (
	_ ports.WebSearcher   = (*Client)(nil)
	_ ports.WebResearcher = (*Client)(nil)
)
