// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"context"
	"encoding/json"
	"log/slog"
	"strings"
	"time"

	"github.com/alicangunduz/raggie/services/edge/internal/config"
	"github.com/alicangunduz/raggie/services/edge/internal/locale"
	"github.com/alicangunduz/raggie/services/edge/internal/ports"
)

type searchProgressEmit func(event string, data []byte)

type webSearchPlan struct {
	Queries    []string `json:"queries"`
	Country    string   `json:"country"`
	SearchLang string   `json:"search_lang"`
	Freshness  string   `json:"freshness"`
}

func generateSearchPlan(
	ctx context.Context,
	deps Deps,
	logger *slog.Logger,
	model, question string,
	maxQueries int,
	defCountry, defLang string,
) webSearchPlan {
	if maxQueries <= 0 {
		maxQueries = 6
	}
	fallback := webSearchPlan{Queries: []string{strings.TrimSpace(question)}, Country: defCountry, SearchLang: defLang}
	genCtx, cancel := context.WithTimeout(ctx, 20*time.Second)
	defer cancel()
	msgs := []ports.Message{
		{Role: ports.RoleSystem, Content: searchPlanFor(requestLocale(ctx), defCountry)},
		{Role: ports.RoleUser, Content: question},
	}
	stream, err := deps.Chat.Stream(genCtx, ports.ChatRequest{
		Messages: msgs, Model: model, Temperature: 0, MaxTokens: 500,
	})
	if err != nil {
		if logger != nil {
			logger.Warn("web plan generation failed; using original question", "err", err)
		}
		return fallback
	}
	var b strings.Builder
	for chunk := range stream {
		if chunk.Err != nil {
			if logger != nil {
				logger.Warn("web plan stream failed; using original question", "err", chunk.Err)
			}
			return fallback
		}
		if chunk.Done {
			break
		}
		b.WriteString(chunk.Delta)
	}
	return parseSearchPlan(b.String(), question, maxQueries, defCountry, defLang)
}

func parseSearchPlan(raw, question string, maxQueries int, defCountry, defLang string) webSearchPlan {
	out := webSearchPlan{Country: defCountry, SearchLang: defLang}
	if obj := extractJSONObject(raw); obj != "" {
		_ = json.Unmarshal([]byte(obj), &out)
	}
	if len(out.Queries) == 0 {
		out.Queries = parseSubQueries(raw, question, maxQueries)
	}
	out.Queries = cleanQueryList(out.Queries, question, maxQueries)
	if out.Country == "" {
		out.Country = defCountry
	}
	if out.SearchLang == "" {
		out.SearchLang = defLang
	}
	return out
}

func generateFollowupQueries(
	ctx context.Context,
	deps Deps,
	logger *slog.Logger,
	model, question string,
	evidence []ports.WebResult,
	maxQueries int,
) []string {
	if maxQueries <= 0 || len(evidence) == 0 {
		return nil
	}
	var b strings.Builder
	b.WriteString("SORU:\n")
	b.WriteString(question)
	b.WriteString("\n\nTOPLANAN KANITLAR:\n")
	for i, r := range evidence {
		if i >= 8 {
			break
		}
		b.WriteString("- ")
		b.WriteString(r.Title)
		b.WriteString(" | ")
		b.WriteString(r.URL)
		b.WriteString(" | ")
		b.WriteString(webResultEvidenceText(r))
		b.WriteByte('\n')
	}
	genCtx, cancel := context.WithTimeout(ctx, 20*time.Second)
	defer cancel()
	stream, err := deps.Chat.Stream(genCtx, ports.ChatRequest{
		Messages: []ports.Message{
			{Role: ports.RoleSystem, Content: locale.Pick(followupQueryPrompt, requestLocale(ctx))},
			{Role: ports.RoleUser, Content: b.String()},
		},
		Model:       model,
		Temperature: 0,
		MaxTokens:   220,
	})
	if err != nil {
		if logger != nil {
			logger.Warn("deep follow-up query generation failed", "err", err)
		}
		return nil
	}
	var raw strings.Builder
	for chunk := range stream {
		if chunk.Err != nil {
			if logger != nil {
				logger.Warn("deep follow-up stream failed", "err", chunk.Err)
			}
			return nil
		}
		if chunk.Done {
			break
		}
		raw.WriteString(chunk.Delta)
	}
	plan := parseSearchPlan(raw.String(), "", maxQueries, "", "")
	return cleanQueryList(plan.Queries, "", maxQueries)
}

func cleanQueryList(in []string, original string, maxQueries int) []string {
	if maxQueries <= 0 {
		maxQueries = len(in)
	}
	out := make([]string, 0, maxQueries)
	seen := map[string]bool{}
	add := func(q string) {
		q = strings.TrimSpace(q)
		q = strings.TrimLeft(q, "-*•0123456789.)( \t")
		q = strings.Trim(q, "\"'`")
		if q == "" || len([]rune(q)) > 300 {
			return
		}
		key := strings.ToLower(q)
		if seen[key] || len(out) >= maxQueries {
			return
		}
		seen[key] = true
		out = append(out, q)
	}
	add(original)
	for _, q := range in {
		add(q)
	}
	return out
}

func singleWebResearch(ctx context.Context, deps Deps, logger *slog.Logger, cfg config.Config, question, query string) []ports.WebResult {
	opts := webResearchOptions(cfg, false)
	results := runWebResearch(ctx, deps, logger, question, []string{query}, opts)
	return rankWebResults(ctx, deps, logger, question, results, opts.EvidenceTopK)
}

func deepWebResearch(
	ctx context.Context,
	deps Deps,
	logger *slog.Logger,
	cfg config.Config,
	model, question string,
	emit searchProgressEmit,
) ([]string, []ports.WebResult) {
	if cfg.DeepSearchTotalTimeoutSeconds > 0 {
		var cancel context.CancelFunc
		ctx, cancel = context.WithTimeout(ctx, time.Duration(cfg.DeepSearchTotalTimeoutSeconds)*time.Second)
		defer cancel()
	}
	progress(emit, "planning")
	plan := generateSearchPlan(
		ctx,
		deps,
		logger,
		model,
		question,
		cfg.DeepSearchMaxQueries,
		cfg.WebSearchCountry,
		cfg.WebSearchLang,
	)
	queries := plan.Queries
	emitDeepQueries(emit, queries)
	progress(emit, "searching")
	progress(emit, "reading")
	opts := webResearchOptions(cfg, true)
	opts.Country = firstNonEmpty(plan.Country, opts.Country)
	opts.SearchLang = firstNonEmpty(plan.SearchLang, opts.SearchLang)
	opts.UILang = opts.SearchLang
	opts.Freshness = plan.Freshness
	// The parent context above is the single end-to-end budget across planning,
	// initial research, reflection, follow-up research, and reranking.
	opts.TotalTimeoutSecs = 0
	results := runWebResearch(ctx, deps, logger, question, queries, opts)
	progress(emit, "reranking")
	results = rankWebResults(ctx, deps, logger, question, results, opts.EvidenceTopK)

	if cfg.DeepSearchFollowupRounds > 0 && len(results) > 0 {
		progress(emit, "reflecting")
		follow := generateFollowupQueries(ctx, deps, logger, model, question, results, 2)
		if len(follow) > 0 {
			queries = append(queries, follow...)
			emitDeepQueries(emit, queries)
			progress(emit, "searching")
			progress(emit, "reading")
			more := runWebResearch(ctx, deps, logger, question, follow, opts)
			progress(emit, "reranking")
			results = mergeWebResults(results, more)
			results = rankWebResults(ctx, deps, logger, question, results, opts.EvidenceTopK)
		}
	}
	return queries, results
}

func runWebResearch(ctx context.Context, deps Deps, logger *slog.Logger, question string, queries []string, opts ports.WebResearchOptions) []ports.WebResult {
	if deps.WebResearch != nil {
		rs, err := deps.WebResearch.Research(ctx, question, queries, opts)
		if err != nil {
			if logger != nil {
				logger.Warn("web research failed; falling back to basic search", "err", err)
			}
		} else {
			return rs
		}
	}
	if deps.Web == nil {
		return nil
	}
	out := make([]ports.WebResult, 0, opts.MaxResults)
	seen := map[string]bool{}
	for _, q := range queries {
		if ctx.Err() != nil || len(out) >= opts.MaxResults {
			break
		}
		rs, err := deps.Web.Search(ctx, q, opts.TopN)
		if err != nil {
			if logger != nil {
				logger.Warn("web search failed; continuing", "err", err, queryLogAttr(q))
			}
			continue
		}
		for _, r := range rs {
			if r.URL == "" || seen[r.URL] {
				continue
			}
			if r.Query == "" {
				r.Query = q
			}
			if r.ReadStatus == "" {
				r.ReadStatus = "snippet_only"
			}
			seen[r.URL] = true
			out = append(out, r)
			if len(out) >= opts.MaxResults {
				break
			}
		}
	}
	return out
}

func webResearchOptions(cfg config.Config, deep bool) ports.WebResearchOptions {
	if deep {
		return ports.WebResearchOptions{
			TopN:             cfg.DeepSearchTopN,
			MaxResults:       cfg.DeepSearchMaxResults,
			ReadEnabled:      cfg.WebSearchReadEnabled,
			ReadTopN:         cfg.DeepSearchReadTopN,
			EvidenceTopK:     cfg.DeepSearchEvidenceTopK,
			QueryConcurrency: cfg.DeepSearchParallelism,
			FetchConcurrency: cfg.WebSearchFetchConcurrency,
			FetchTimeout:     cfg.WebSearchFetchTimeoutSeconds,
			MaxBodyBytes:     cfg.WebSearchMaxBodyBytes,
			Country:          cfg.WebSearchCountry,
			SearchLang:       cfg.WebSearchLang,
			UILang:           cfg.WebSearchLang,
			ResultFilter:     "web",
			ExtraSnippets:    true,
			TotalTimeoutSecs: cfg.DeepSearchTotalTimeoutSeconds,
		}
	}
	return ports.WebResearchOptions{
		TopN:             cfg.WebSearchTopN,
		MaxResults:       max(cfg.WebSearchTopN, cfg.WebSearchReadTopN),
		ReadEnabled:      cfg.WebSearchReadEnabled,
		ReadTopN:         cfg.WebSearchReadTopN,
		EvidenceTopK:     cfg.WebSearchReadTopN,
		QueryConcurrency: 1,
		FetchConcurrency: cfg.WebSearchFetchConcurrency,
		FetchTimeout:     cfg.WebSearchFetchTimeoutSeconds,
		MaxBodyBytes:     cfg.WebSearchMaxBodyBytes,
		Country:          cfg.WebSearchCountry,
		SearchLang:       cfg.WebSearchLang,
		UILang:           cfg.WebSearchLang,
		ResultFilter:     "web",
		ExtraSnippets:    true,
		TotalTimeoutSecs: cfg.DeepSearchTotalTimeoutSeconds,
	}
}

func rankWebResults(ctx context.Context, deps Deps, logger *slog.Logger, question string, results []ports.WebResult, topK int) []ports.WebResult {
	if topK <= 0 || topK > len(results) {
		topK = len(results)
	}
	if len(results) <= 1 || deps.WebReranker == nil {
		return append([]ports.WebResult(nil), results[:topK]...)
	}
	docs := make([]string, len(results))
	for i, r := range results {
		docs[i] = webResultEvidenceText(r)
	}
	hits, err := deps.WebReranker.Rerank(ctx, question, docs, topK)
	if err != nil || len(hits) == 0 {
		if err != nil && logger != nil {
			logger.Warn("web evidence rerank failed; keeping search order", "err", err)
		}
		return append([]ports.WebResult(nil), results[:topK]...)
	}
	out := make([]ports.WebResult, 0, topK)
	seen := map[int]bool{}
	for _, h := range hits {
		if h.Index < 0 || h.Index >= len(results) || seen[h.Index] {
			continue
		}
		r := results[h.Index]
		r.Score = h.Score
		out = append(out, r)
		seen[h.Index] = true
		if len(out) >= topK {
			return out
		}
	}
	for i, r := range results {
		if seen[i] {
			continue
		}
		out = append(out, r)
		if len(out) >= topK {
			break
		}
	}
	return out
}

func mergeWebResults(a, b []ports.WebResult) []ports.WebResult {
	out := make([]ports.WebResult, 0, len(a)+len(b))
	seen := map[string]bool{}
	for _, list := range [][]ports.WebResult{a, b} {
		for _, r := range list {
			if r.URL == "" || seen[r.URL] {
				continue
			}
			seen[r.URL] = true
			out = append(out, r)
		}
	}
	return out
}

func webResultEvidenceText(r ports.WebResult) string {
	parts := []string{r.Title, r.Snippet}
	parts = append(parts, r.ExtraSnippets...)
	if r.Excerpt != "" {
		parts = append(parts, webPageContentLabel+r.Excerpt)
	}
	return strings.TrimSpace(strings.Join(nonEmpty(parts), "\n"))
}

func webEvidenceContextBlock(results []ports.WebResult) string {
	return webEvidenceContextBlockFrom(results, 1)
}

func webEvidenceContextBlockFrom(results []ports.WebResult, firstCitation int) string {
	if firstCitation < 1 {
		firstCitation = 1
	}
	var b strings.Builder
	for i, wr := range results {
		title := wr.Title
		if title == "" {
			title = wr.URL
		}
		b.WriteString("[")
		b.WriteString(jsonNumber(firstCitation + i))
		b.WriteString("] (source: ")
		b.WriteString(title)
		b.WriteString(" - ")
		b.WriteString(wr.URL)
		b.WriteString(")\n")
		b.WriteString(webResultEvidenceText(wr))
		b.WriteString("\n\n")
	}
	return b.String()
}

func jsonNumber(n int) string {
	b, _ := json.Marshal(n)
	return string(b)
}

func webSourceCards(results []ports.WebResult) []map[string]any {
	webSrc := make([]map[string]any, 0, len(results))
	for _, wr := range results {
		webSrc = append(webSrc, map[string]any{
			"type":         "web",
			"title":        wr.Title,
			"url":          wr.URL,
			"text":         webResultEvidenceText(wr),
			"query":        wr.Query,
			"retrieved_at": wr.RetrievedAt,
			"excerpt":      wr.Excerpt,
			"read_status":  wr.ReadStatus,
			"score":        wr.Score,
		})
	}
	return webSrc
}

func documentSourceCards(chunks []ports.Chunk) []map[string]any {
	docSrc := make([]map[string]any, 0, len(chunks))
	for _, chunk := range chunks {
		docSrc = append(docSrc, map[string]any{
			"type":        "doc",
			"document_id": chunk.DocumentID,
			"filename":    chunk.Filename,
			"text":        chunk.Text,
			"score":       chunk.Score,
		})
	}
	return docSrc
}

func combinedSourceCards(chunks []ports.Chunk, webResults []ports.WebResult) []map[string]any {
	out := documentSourceCards(chunks)
	out = append(out, webSourceCards(webResults)...)
	return out
}

func progress(emit searchProgressEmit, status string) {
	if emit == nil {
		return
	}
	emit("search_progress", mustJSON(map[string]string{"status": status}))
}

func emitDeepQueries(emit searchProgressEmit, queries []string) {
	if emit == nil {
		return
	}
	emit("deep_progress", mustJSON(map[string][]string{"queries": queries}))
}

func nonEmpty(in []string) []string {
	out := make([]string, 0, len(in))
	for _, s := range in {
		if s = strings.TrimSpace(s); s != "" {
			out = append(out, s)
		}
	}
	return out
}

func firstNonEmpty(values ...string) string {
	for _, v := range values {
		if strings.TrimSpace(v) != "" {
			return v
		}
	}
	return ""
}
