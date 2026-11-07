// SPDX-License-Identifier: Apache-2.0

// Package rag orchestrates the synchronous retrieval hot path: embed the
// question, search Qdrant (workspace-filtered), optionally rerank the candidates
// with a cross-encoder, trim to the context window, and assemble the prompt.
// This is the work measured by acceptance criterion A2 (<200ms, cache-warm;
// reranking, when enabled, adds to this and is bounded + fail-open).
package rag

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"strings"
	"time"

	"github.com/alicangunduz/raggie/services/edge/internal/locale"
	"github.com/alicangunduz/raggie/services/edge/internal/logthrottle"
	"github.com/alicangunduz/raggie/services/edge/internal/ports"
)

// missingCollectionLogInterval bounds the "collection missing" warning: on a
// fresh install every chat hits it until the first document is indexed.
const missingCollectionLogInterval = time.Minute

// answerStyleHint returns the style instruction for a style in the given
// locale, or "" for empty/unknown/balanced.
func answerStyleHint(style string, loc locale.Locale) string {
	return locale.Pick(answerStyleHints, loc)[strings.TrimSpace(strings.ToLower(style))]
}

// Option configures a RAGService.
type Option func(*RAGService)

// WithReranker enables cross-encoder reranking of candidate chunks before they
// are trimmed to the context window. The default (no reranker) keeps Qdrant's
// dense similarity order.
func WithReranker(r ports.Reranker) Option { return func(s *RAGService) { s.reranker = r } }

// WithRerankCandidateK bounds expensive cross-encoder work while preserving the
// full fused candidate list for diversity/backfill. Zero reranks every candidate.
func WithRerankCandidateK(n int) Option {
	return func(s *RAGService) { s.rerankCandidateK = n }
}

// WithLowConfidenceScore sets the score floor below which the model is hinted
// that context may be weak. <= 0 disables the hint.
func WithLowConfidenceScore(f float32) Option {
	return func(s *RAGService) { s.lowConfidenceScore = f }
}

// WithLogger sets the logger for retrieval warnings (default slog.Default()).
func WithLogger(l *slog.Logger) Option {
	return func(s *RAGService) {
		if l != nil {
			s.logger = l
		}
	}
}

// WithMaxChunksPerDocument sets a soft context-packing diversity cap. Skipped
// chunks are used as backfill when there are not enough distinct documents.
func WithMaxChunksPerDocument(n int) Option {
	return func(s *RAGService) { s.maxChunksPerDocument = n }
}

// RAGService holds the retrieval ports. Chat streaming is handled separately by
// the HTTP layer so retrieval timing (A2) is isolated from the LLM stream.
type RAGService struct {
	queryEmbedder        ports.QueryEmbedder
	vectorStore          ports.VectorStore
	reranker             ports.Reranker // optional; nil keeps fused order
	rerankCandidateK     int            // <= 0 reranks every fused candidate
	lowConfidenceScore   float32        // <= 0 disables the low-confidence hint
	maxChunksPerDocument int            // <= 0 disables source diversity packing
	logger               *slog.Logger
	missingCollectionLog *logthrottle.Throttle
}

func New(queryEmbedder ports.QueryEmbedder, vectorStore ports.VectorStore, opts ...Option) *RAGService {
	s := &RAGService{
		queryEmbedder:        queryEmbedder,
		vectorStore:          vectorStore,
		logger:               slog.Default(),
		missingCollectionLog: logthrottle.New(missingCollectionLogInterval),
	}
	for _, o := range opts {
		o(s)
	}
	return s
}

// RetrieveResult is the outcome of the A2-scoped retrieval step.
type RetrieveResult struct {
	ContextText   string
	Chunks        []ports.Chunk
	LowConfidence bool // best chunk scored below the configured floor
	Duration      time.Duration
}

// Retrieve embeds the question, pulls candidateK workspace-filtered chunks from
// Qdrant, optionally reranks them, trims to contextK, and assembles the labeled
// context text. Duration is the A2 measurement.
func (s *RAGService) Retrieve(ctx context.Context, workspaceIDs []string, question string, candidateK, contextK int) (RetrieveResult, error) {
	start := time.Now()
	// Defensive floors so a mis-set config never sends Limit:0 to Qdrant.
	if candidateK <= 0 {
		candidateK = 8
	}
	if contextK <= 0 {
		contextK = candidateK
	}

	query, err := s.queryEmbedder.EmbedQuery(ctx, question)
	if err != nil {
		return RetrieveResult{}, err
	}
	if len(query.Dense) == 0 {
		return RetrieveResult{}, errors.New("query embedder returned no dense vector")
	}
	chunks, err := s.vectorStore.Search(ctx, workspaceIDs, query, candidateK)
	if errors.Is(err, ports.ErrCollectionMissing) {
		// Nothing indexed under the active embedding profile yet (fresh install,
		// or a profile switch before re-embedding): answer from no documents
		// rather than failing the chat.
		if ok, suppressed := s.missingCollectionLog.Allow(); ok {
			s.logger.Warn("vector collection missing; retrieval returns no documents until it is indexed",
				"collection", query.Collection, "fingerprint", query.Fingerprint,
				"err", err, "suppressed", suppressed)
		}
		return RetrieveResult{Duration: time.Since(start)}, nil
	}
	if err != nil {
		return RetrieveResult{}, err
	}

	// Optional cross-encoder rerank: reorder candidates by query–passage
	// relevance, then trim to the context window. Any failure (reranker down,
	// timeout, empty result) leaves the dense similarity order untouched —
	// retrieval never blocks on the reranker.
	if s.reranker != nil && len(chunks) > 1 {
		rerankN := len(chunks)
		if s.rerankCandidateK > 0 && rerankN > s.rerankCandidateK {
			rerankN = s.rerankCandidateK
		}
		docs := make([]string, rerankN)
		for i, c := range chunks[:rerankN] {
			docs[i] = c.Text
		}
		if hits, rerr := s.reranker.Rerank(ctx, question, docs, rerankN); rerr == nil && len(hits) > 0 {
			reordered := make([]ports.Chunk, 0, len(chunks))
			seen := make(map[int]bool, len(hits))
			for _, h := range hits {
				if h.Index >= 0 && h.Index < rerankN && !seen[h.Index] {
					c := chunks[h.Index]
					c.Score = h.Score // surface the rerank score in citations
					reordered = append(reordered, c)
					seen[h.Index] = true
				}
			}
			// Some providers return fewer than topN hits. Preserve every omitted
			// candidate in its original fused order so diversity/backfill still
			// has the full recall set available.
			for i, c := range chunks[:rerankN] {
				if !seen[i] {
					reordered = append(reordered, c)
				}
			}
			reordered = append(reordered, chunks[rerankN:]...)
			chunks = reordered
		}
	}

	if hasDocumentOutlineIntent(question) {
		chunks = promoteDocumentOutlines(chunks)
	}
	chunks = selectContextChunks(chunks, contextK, s.maxChunksPerDocument)

	lowConfidence := s.lowConfidenceScore > 0 && len(chunks) > 0 && chunks[0].Score < s.lowConfidenceScore

	var b strings.Builder
	for i, c := range chunks {
		src := c.Filename
		if src == "" {
			src = "document"
		}
		kind := ""
		if c.ChunkKind == "outline" {
			kind = ", " + labelOutline
		}
		fmt.Fprintf(&b, "[%d] (%s: %s%s, %s: %.2f)\n%s\n\n", i+1, labelSource, src, kind, labelRelevance, c.Score, c.Text)
	}
	return RetrieveResult{
		ContextText:   b.String(),
		Chunks:        chunks,
		LowConfidence: lowConfidence,
		Duration:      time.Since(start),
	}, nil
}

func hasDocumentOutlineIntent(question string) bool {
	q := strings.ToLower(strings.Join(strings.Fields(question), " "))
	hasHeadingWord := strings.Contains(q, "başlık") || strings.Contains(q, "başlığ")
	if hasHeadingWord &&
		(strings.Contains(q, "ana") || strings.Contains(q, "hangi") || strings.Contains(q, "liste")) {
		return true
	}
	for _, marker := range []string{
		"ana başlık",
		"hangi başlık",
		"başlıkları",
		"bölüm listesi",
		"hangi bölüm",
		"bölümleri",
		"bölüm yapısı",
		"neleri kapsıyor",
		"hangi konuları kapsıyor",
		"içindekiler",
		"table of contents",
		"main heading",
		"main section",
		"which section",
		"what does it cover",
	} {
		if strings.Contains(q, marker) {
			return true
		}
	}
	return false
}

// promoteDocumentOutlines keeps the fused document order, but places an
// available outline immediately before the first hit from that document. This
// lets the normal per-document diversity cap retain the document structure for
// section-list questions without polluting ordinary detail queries.
func promoteDocumentOutlines(chunks []ports.Chunk) []ports.Chunk {
	outlineByDocument := make(map[string]ports.Chunk)
	for _, chunk := range chunks {
		if chunk.ChunkKind != "outline" {
			continue
		}
		if key := chunkDocumentKey(chunk); key != "" {
			outlineByDocument[key] = chunk
		}
	}
	if len(outlineByDocument) == 0 {
		return chunks
	}

	out := make([]ports.Chunk, 0, len(chunks))
	emittedOutline := make(map[string]bool)
	for _, chunk := range chunks {
		key := chunkDocumentKey(chunk)
		if key != "" && !emittedOutline[key] {
			if outline, ok := outlineByDocument[key]; ok {
				out = append(out, outline)
				emittedOutline[key] = true
			}
		}
		if chunk.ChunkKind == "outline" && key != "" && emittedOutline[key] {
			continue
		}
		out = append(out, chunk)
	}
	return out
}

func chunkDocumentKey(chunk ports.Chunk) string {
	if chunk.DocumentID != "" {
		return chunk.DocumentID
	}
	return chunk.Filename
}

func selectContextChunks(chunks []ports.Chunk, limit, maxPerDocument int) []ports.Chunk {
	if limit <= 0 || len(chunks) == 0 {
		return nil
	}

	// Exact normalized duplicates commonly arise from overlap/re-ingestion and
	// waste context tokens without adding evidence.
	unique := make([]ports.Chunk, 0, len(chunks))
	seenText := make(map[string]bool, len(chunks))
	for _, chunk := range chunks {
		documentKey := chunkDocumentKey(chunk)
		textKey := strings.ToLower(strings.Join(strings.Fields(chunk.Text), " "))
		dedupeKey := ""
		if documentKey != "" && textKey != "" {
			dedupeKey = documentKey + "\x00" + textKey
		}
		if dedupeKey != "" && seenText[dedupeKey] {
			continue
		}
		if dedupeKey != "" {
			seenText[dedupeKey] = true
		}
		unique = append(unique, chunk)
	}
	if maxPerDocument <= 0 {
		if len(unique) > limit {
			unique = unique[:limit]
		}
		return unique
	}

	selected := make([]ports.Chunk, 0, min(limit, len(unique)))
	overflow := make([]ports.Chunk, 0)
	perDocument := make(map[string]int)
	for _, chunk := range unique {
		documentKey := chunkDocumentKey(chunk)
		if documentKey != "" && perDocument[documentKey] >= maxPerDocument {
			overflow = append(overflow, chunk)
			continue
		}
		selected = append(selected, chunk)
		if documentKey != "" {
			perDocument[documentKey]++
		}
		if len(selected) >= limit {
			return selected
		}
	}
	for _, chunk := range overflow {
		selected = append(selected, chunk)
		if len(selected) >= limit {
			break
		}
	}
	return selected
}

// Source kinds for the unified ContextSource union. Each kind carries its
// own [n]-labeled grounding text and selects the matching grounding
// instructions when it is the sole/primary source.
const (
	SourceDocuments = "documents" // private-document RAG context (always-on grounding)
	SourceWeb       = "web"       // single web-search results
	SourceDeep      = "deep"      // deep-research deduped web results
)

// ContextSource is one grounding block fed to the unified message assembler.
// Text is the already-[n]-labeled grounding (e.g. the RAG context built by
// Retrieve, or webContextBlock output). LowConfidence applies only to documents
// (it adds the soft "context may be weak" hint).
type ContextSource struct {
	Kind          string
	Text          string
	LowConfidence bool
}

// AssembleMessages builds the LLM message list: a grounded system prompt + the
// retrieved context, the last maxHistory messages of conversation memory, then
// the question. maxHistory <= 0 disables history. When contextText is empty the
// only genuine "not found" path is taken; lowConfidence appends a soft hint.
//
// It is a thin shim over AssembleUnifiedMessages with a single documents source,
// so the documents path (and its tests) are unchanged.
func (s *RAGService) AssembleMessages(
	systemPrompt string, history []ports.Message, contextText, question string, maxHistory int, lowConfidence bool, persona, answerStyle string, loc locale.Locale,
) []ports.Message {
	return s.AssembleUnifiedMessages(systemPrompt, history,
		[]ContextSource{{Kind: SourceDocuments, Text: contextText, LowConfidence: lowConfidence}},
		question, maxHistory, persona, answerStyle, loc)
}

// AssembleUnifiedMessages composes ONE grounded prompt from a union of context
// sources. RAG documents are always-on grounding; web/deep are folded in
// when their tools ran. The grounding instructions are chosen by the union's
// composition so existing single-source behaviour is preserved byte-for-byte:
//   - documents-only (possibly empty) → the documents grounding / not-found path,
//     matching the legacy AssembleMessages.
//   - web-only → the web fallback grounding (legacy AssembleWebMessages).
//   - deep-only → the deep-research grounding (legacy AssembleDeepMessages).
//   - a mix → documents grounding plus a labeled web block appended, so a single
//     answer can cite both private docs and the web.
//
// loc selects the template language (instructions, section headers); the
// model is always told to answer in the language of the question.
func (s *RAGService) AssembleUnifiedMessages(
	systemPrompt string, history []ports.Message, sources []ContextSource, question string, maxHistory int, persona, answerStyle string, loc locale.Locale,
) []ports.Message {
	sys := systemPrompt
	if strings.TrimSpace(sys) == "" {
		sys = locale.Pick(defaultSystemPrompt, loc)
	}
	h := locale.Pick(headers, loc)

	// Partition the union by kind, keeping only non-empty text blocks.
	var docs *ContextSource
	var web, deep string
	for i := range sources {
		src := sources[i]
		if strings.TrimSpace(src.Text) == "" && src.Kind != SourceDocuments {
			continue
		}
		switch src.Kind {
		case SourceDocuments:
			cp := src
			docs = &cp
		case SourceWeb:
			web = src.Text
		case SourceDeep:
			deep = src.Text
		}
	}

	hasDocs := docs != nil && strings.TrimSpace(docs.Text) != ""
	hasWeb := strings.TrimSpace(web) != ""
	hasDeep := strings.TrimSpace(deep) != ""

	switch {
	case !hasDocs && !hasWeb && hasDeep:
		// Deep-only: identical to the legacy deep-research grounding.
		sys += locale.Pick(deepGroundingInstructions, loc)
		sys += "\n\n" + h.web + "\n" + deep
	case !hasDocs && hasWeb && !hasDeep:
		// Web-only: identical to the legacy web fallback grounding.
		sys += locale.Pick(webGroundingInstructions, loc)
		sys += "\n\n" + h.web + "\n" + web
	case !hasDocs && !hasWeb && !hasDeep:
		// No grounding at all: the only genuine "not found" path.
		sys += locale.Pick(emptyContextInstructions, loc)
	default:
		// Documents are present (alone or composed with web/deep): the documents
		// grounding leads, and any web/deep blocks are appended so the answer can
		// cite both private docs and the web in one turn.
		sys += locale.Pick(groundingInstructions, loc)
		if docs != nil && docs.LowConfidence {
			sys += locale.Pick(lowConfidenceHint, loc)
		}
		if hasDocs {
			sys += "\n\n" + h.context + "\n" + docs.Text
		}
		if hasDeep {
			sys += "\n\n" + h.deep + "\n" + deep
		}
		if hasWeb {
			sys += "\n\n" + h.web + "\n" + web
		}
	}

	if strings.TrimSpace(persona) != "" {
		sys += "\n\n" + persona
	}
	if hint := answerStyleHint(answerStyle, loc); hint != "" {
		sys += "\n\n" + hint
	}

	if maxHistory > 0 && len(history) > maxHistory {
		history = history[len(history)-maxHistory:]
	} else if maxHistory <= 0 {
		history = nil
	}
	msgs := make([]ports.Message, 0, len(history)+2)
	msgs = append(msgs, ports.Message{Role: ports.RoleSystem, Content: sys})
	msgs = append(msgs, history...)
	msgs = append(msgs, ports.Message{Role: ports.RoleUser, Content: question})
	return msgs
}

// AssembleDeepMessages builds the LLM message list for the deep-research web
// mode: a deep-synthesis system prompt + the deduped [n] results (already
// collected across all sub-queries), conversation memory, then the question.
// A thin shim over AssembleUnifiedMessages with a single deep source, so the
// deep path (and its tests) are unaffected.
func (s *RAGService) AssembleDeepMessages(
	systemPrompt string, history []ports.Message, webContext, question string, maxHistory int, persona, answerStyle string, loc locale.Locale,
) []ports.Message {
	return s.AssembleUnifiedMessages(systemPrompt, history,
		[]ContextSource{{Kind: SourceDeep, Text: webContext}},
		question, maxHistory, persona, answerStyle, loc)
}

// AssembleWebMessages builds the LLM message list for the web-search fallback:
// a web-grounded system prompt + the [n] results, conversation memory, then
// the question. A thin shim over AssembleUnifiedMessages with a single web
// source, so the single-web path (and its tests) are unaffected.
func (s *RAGService) AssembleWebMessages(
	systemPrompt string, history []ports.Message, webContext, question string, maxHistory int, persona, answerStyle string, loc locale.Locale,
) []ports.Message {
	return s.AssembleUnifiedMessages(systemPrompt, history,
		[]ContextSource{{Kind: SourceWeb, Text: webContext}},
		question, maxHistory, persona, answerStyle, loc)
}
