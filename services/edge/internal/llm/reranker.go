// SPDX-License-Identifier: Apache-2.0

package llm

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"sync/atomic"
	"time"

	"github.com/alicangunduz/raggie/services/edge/internal/logthrottle"
	"github.com/alicangunduz/raggie/services/edge/internal/outboundhttp"
	"github.com/alicangunduz/raggie/services/edge/internal/ports"
)

// DefaultRerankTimeout bounds one POST /v1/rerank when no timeout is configured
// (RERANK_TIMEOUT_MS).
const DefaultRerankTimeout = 5 * time.Second

// rerankFailOpenLogInterval rate-limits the fail-open warning: a degraded
// reranker would otherwise log on every chat turn.
const rerankFailOpenLogInterval = time.Minute

// Reranker calls the embeddings gateway's /v1/rerank endpoint (a multilingual
// cross-encoder, local or cloud). It implements ports.Reranker and shares the
// gateway base URL and internal bearer token with the QueryEmbedder.
//
// The timeout is deliberately generous: the first call after a cold start may
// trigger a one-time model load on the gateway side. A miss (timeout, non-200,
// malformed body, pool full) returns an error and the caller keeps the fused
// order — reranking is strictly best-effort. Every such fail-open is counted
// (raggie_edge_rerank_fail_open_total) and logged at a bounded rate.
type Reranker struct {
	baseURL string
	token   string // INTERNAL_API_SECRET; empty sends no Authorization header
	http    *http.Client
	pool    *pool
	logger  *slog.Logger

	failOpen    atomic.Int64
	failOpenLog *logthrottle.Throttle
}

// NewReranker builds the /v1/rerank client. bearerToken is the internal API
// secret (never the LLM provider key); timeout <= 0 uses DefaultRerankTimeout.
func NewReranker(baseURL, bearerToken string, timeout time.Duration, maxConcurrency int) *Reranker {
	if timeout <= 0 {
		timeout = DefaultRerankTimeout
	}
	return &Reranker{
		baseURL:     baseURL,
		token:       bearerToken,
		http:        outboundhttp.NewClient(timeout),
		pool:        newPool(maxConcurrency),
		logger:      slog.Default(),
		failOpenLog: logthrottle.New(rerankFailOpenLogInterval),
	}
}

// WithLogger sets the logger for the fail-open warning.
func (r *Reranker) WithLogger(l *slog.Logger) *Reranker {
	if l != nil {
		r.logger = l
	}
	return r
}

// FailOpenTotal is the number of rerank calls that failed open (callers kept
// the fused order) since start; exported as raggie_edge_rerank_fail_open_total.
func (r *Reranker) FailOpenTotal() int64 { return r.failOpen.Load() }

type rerankRequest struct {
	Query     string   `json:"query"`
	Documents []string `json:"documents"`
	TopN      int      `json:"top_n,omitempty"`
}

type rerankResponse struct {
	Results []struct {
		Index int     `json:"index"`
		Score float32 `json:"score"`
	} `json:"results"`
}

func (r *Reranker) Rerank(ctx context.Context, query string, documents []string, topN int) ([]ports.RerankHit, error) {
	if len(documents) == 0 {
		return nil, nil
	}
	hits, err := r.rerank(ctx, query, documents, topN)
	// A request its caller already abandoned is not a reranker failure.
	if err != nil && ctx.Err() == nil {
		r.failOpen.Add(1)
		if ok, suppressed := r.failOpenLog.Allow(); ok {
			r.logger.Warn("rerank failed open; keeping the fused retrieval order",
				"err", err, "candidates", len(documents), "suppressed", suppressed)
		}
	}
	return hits, err
}

func (r *Reranker) rerank(ctx context.Context, query string, documents []string, topN int) ([]ports.RerankHit, error) {
	if !r.pool.tryAcquire() {
		return nil, ErrUpstreamBusy
	}
	defer r.pool.release()

	payload, _ := json.Marshal(rerankRequest{Query: query, Documents: documents, TopN: topN})
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, r.baseURL+"/rerank", bytes.NewReader(payload))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	setBearer(req, r.token)

	resp, err := r.http.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 4<<10))
		return nil, gatewayStatusError("rerank", resp.StatusCode)
	}

	var body rerankResponse
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		return nil, err
	}
	hits := make([]ports.RerankHit, 0, len(body.Results))
	for _, res := range body.Results {
		hits = append(hits, ports.RerankHit{Index: res.Index, Score: res.Score})
	}
	return hits, nil
}

var _ ports.Reranker = (*Reranker)(nil)
