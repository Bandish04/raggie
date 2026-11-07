// SPDX-License-Identifier: Apache-2.0

package llm

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/alicangunduz/raggie/services/edge/internal/logthrottle"
	"github.com/alicangunduz/raggie/services/edge/internal/outboundhttp"
	"github.com/alicangunduz/raggie/services/edge/internal/ports"
)

// DefaultEmbedQueryTimeout bounds one POST /v1/query when no timeout is
// configured (EMBED_QUERY_TIMEOUT_MS).
const DefaultEmbedQueryTimeout = 8 * time.Second

const (
	// infoRetryInterval bounds how often readiness re-asks GET /v1/info while
	// the profile is unknown, so an older gateway is not hammered.
	infoRetryInterval = 30 * time.Second
	// maxInfoBodyBytes caps the /v1/info body (a few hundred bytes in practice).
	maxInfoBodyBytes    = 64 << 10
	profileLogInterval  = time.Minute
	infoFailLogInterval = 5 * time.Minute
)

// ErrEmbeddingsUnauthorized means the embeddings gateway rejected the edge's
// internal bearer token (HTTP 401/403): every query would fail until the same
// INTERNAL_API_SECRET is configured on both sides.
var ErrEmbeddingsUnauthorized = errors.New(
	"embeddings gateway rejected the internal bearer token (set the same INTERNAL_API_SECRET on the edge and the embeddings gateway)")

// QueryEmbedder calls the embeddings gateway's /v1/query endpoint, which returns
// BOTH the dense vector (with the profile's query prefix/extra applied
// server-side) and the BM25 sparse vector for a single query — one round trip on
// the A2 hot path — together with the Qdrant collection and fingerprint of the
// gateway's active embedding profile. Implements ports.QueryEmbedder.
//
// It also reads the profile itself (GET /v1/info) at startup and lazily from
// readiness, for operator visibility. The profile never overrides a query
// response: a gateway can switch profiles mid-flight, so the collection each
// /v1/query response names is the one searched.
type QueryEmbedder struct {
	baseURL string
	token   string // INTERNAL_API_SECRET; empty sends no Authorization header
	http    *http.Client
	pool    *pool
	logger  *slog.Logger

	info      atomic.Pointer[EmbeddingsInfo] // last profile read; nil = unknown
	infoRetry time.Duration

	infoMu      sync.Mutex // serialises /v1/info fetches and guards the fields below
	infoAttempt time.Time
	infoErr     error

	profileChangeLog *logthrottle.Throttle
	infoFailLog      *logthrottle.Throttle
}

// NewQueryEmbedder builds the /v1/query client. bearerToken is the internal
// API secret (never the LLM provider key); timeout <= 0 uses
// DefaultEmbedQueryTimeout.
func NewQueryEmbedder(baseURL, bearerToken string, timeout time.Duration, maxConcurrency int) *QueryEmbedder {
	if timeout <= 0 {
		timeout = DefaultEmbedQueryTimeout
	}
	return &QueryEmbedder{
		baseURL:          baseURL,
		token:            bearerToken,
		http:             outboundhttp.NewClient(timeout),
		pool:             newPool(maxConcurrency),
		logger:           slog.Default(),
		infoRetry:        infoRetryInterval,
		profileChangeLog: logthrottle.New(profileLogInterval),
		infoFailLog:      logthrottle.New(infoFailLogInterval),
	}
}

// WithLogger sets the logger for profile and degradation messages.
func (e *QueryEmbedder) WithLogger(l *slog.Logger) *QueryEmbedder {
	if l != nil {
		e.logger = l
	}
	return e
}

type queryEmbedResponse struct {
	Dense  []float32 `json:"dense"`
	Sparse struct {
		Indices []uint32  `json:"indices"`
		Values  []float32 `json:"values"`
	} `json:"sparse"`
	// Additive in the gateway contract; absent on an older gateway.
	Collection  string `json:"collection"`
	Fingerprint string `json:"fingerprint"`
}

func (e *QueryEmbedder) EmbedQuery(ctx context.Context, query string) (ports.QueryVectors, error) {
	if !e.pool.tryAcquire() {
		return ports.QueryVectors{}, ErrUpstreamBusy
	}
	defer e.pool.release()

	payload, _ := json.Marshal(map[string]string{"query": query})
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, e.baseURL+"/query", bytes.NewReader(payload))
	if err != nil {
		return ports.QueryVectors{}, err
	}
	req.Header.Set("Content-Type", "application/json")
	setBearer(req, e.token)

	resp, err := e.http.Do(req)
	if err != nil {
		return ports.QueryVectors{}, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 4<<10))
		return ports.QueryVectors{}, gatewayStatusError("query embed", resp.StatusCode)
	}

	var body queryEmbedResponse
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		return ports.QueryVectors{}, err
	}
	_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 4<<10))
	if len(body.Dense) == 0 {
		return ports.QueryVectors{}, fmt.Errorf("query embed: empty dense vector")
	}
	e.observeCollection(body.Collection, body.Fingerprint)
	return ports.QueryVectors{
		Dense:       body.Dense,
		Sparse:      ports.SparseVector{Indices: body.Sparse.Indices, Values: body.Sparse.Values},
		Collection:  body.Collection,
		Fingerprint: body.Fingerprint,
	}, nil
}

// observeCollection compares a query response's collection with the cached
// profile. On a mismatch the per-response value is what gets searched; the
// stale profile is dropped so readiness reads the current one.
func (e *QueryEmbedder) observeCollection(collection, fingerprint string) {
	cached := e.info.Load()
	if collection == "" || cached == nil || cached.Collection == collection {
		return
	}
	if !e.info.CompareAndSwap(cached, nil) {
		return
	}
	if ok, suppressed := e.profileChangeLog.Allow(); ok {
		e.logger.Warn("embeddings gateway collection changed since its profile was read; searching the per-response collection",
			"previous_collection", cached.Collection, "previous_fingerprint", cached.Fingerprint,
			"collection", collection, "fingerprint", fingerprint, "suppressed", suppressed)
	}
}

// EmbeddingsInfo is the gateway's active embedding profile (GET /v1/info).
// Nullable contract fields are flattened to "" (SparseModel: sparse disabled;
// Egress hosts: the text stays on the gateway's server).
type EmbeddingsInfo struct {
	Provider    string
	Model       string
	Dim         int
	Fingerprint string
	Collection  string
	SparseModel string
	Reranker    EmbeddingsRerankerInfo
	Egress      EmbeddingsEgress
}

// EmbeddingsRerankerInfo names the gateway's reranker backend.
type EmbeddingsRerankerInfo struct {
	Provider string
	Model    string
}

// EmbeddingsEgress names the third-party hosts document/query text is sent to.
type EmbeddingsEgress struct {
	DenseHost  string
	RerankHost string
}

type infoWire struct {
	Provider    string  `json:"provider"`
	Model       string  `json:"model"`
	Dim         int     `json:"dim"`
	Fingerprint string  `json:"fingerprint"`
	Collection  string  `json:"collection"`
	SparseModel *string `json:"sparse_model"`
	Reranker    struct {
		Provider string  `json:"provider"`
		Model    *string `json:"model"`
	} `json:"reranker"`
	Egress struct {
		DenseHost  *string `json:"dense_host"`
		RerankHost *string `json:"rerank_host"`
	} `json:"egress"`
}

func deref(s *string) string {
	if s == nil {
		return ""
	}
	return *s
}

// Info returns the last profile read from the gateway, if any.
func (e *QueryEmbedder) Info() (EmbeddingsInfo, bool) {
	if info := e.info.Load(); info != nil {
		return *info, true
	}
	return EmbeddingsInfo{}, false
}

// RefreshInfo reads GET /v1/info, caches the profile and logs it when it
// changed. Errors are returned (and remembered for readiness); a 401/403 wraps
// ErrEmbeddingsUnauthorized.
func (e *QueryEmbedder) RefreshInfo(ctx context.Context) (EmbeddingsInfo, error) {
	e.infoMu.Lock()
	defer e.infoMu.Unlock()
	return e.refreshInfoLocked(ctx)
}

func (e *QueryEmbedder) refreshInfoLocked(ctx context.Context) (EmbeddingsInfo, error) {
	info, err := e.fetchInfo(ctx)
	e.infoAttempt, e.infoErr = time.Now(), err
	if err != nil {
		if ok, suppressed := e.infoFailLog.Allow(); ok {
			e.logger.Warn("embeddings gateway profile unavailable (GET /v1/info); searching the collection each query names",
				"err", err, "suppressed", suppressed)
		}
		return EmbeddingsInfo{}, err
	}
	if prev := e.info.Swap(&info); prev == nil || *prev != info {
		e.logger.Info("embeddings gateway profile",
			"provider", info.Provider, "model", info.Model, "dim", info.Dim,
			"fingerprint", info.Fingerprint, "collection", info.Collection,
			"sparse_model", info.SparseModel,
			"reranker_provider", info.Reranker.Provider, "reranker_model", info.Reranker.Model,
			"egress_dense_host", info.Egress.DenseHost, "egress_rerank_host", info.Egress.RerankHost)
	}
	return info, nil
}

func (e *QueryEmbedder) fetchInfo(ctx context.Context) (EmbeddingsInfo, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, e.baseURL+"/info", nil)
	if err != nil {
		return EmbeddingsInfo{}, err
	}
	setBearer(req, e.token)
	resp, err := e.http.Do(req)
	if err != nil {
		return EmbeddingsInfo{}, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 4<<10))
		return EmbeddingsInfo{}, gatewayStatusError("embeddings info", resp.StatusCode)
	}
	var w infoWire
	if err := json.NewDecoder(io.LimitReader(resp.Body, maxInfoBodyBytes)).Decode(&w); err != nil {
		return EmbeddingsInfo{}, fmt.Errorf("embeddings info: %w", err)
	}
	if w.Provider == "" || w.Dim <= 0 || w.Collection == "" || w.Fingerprint == "" {
		return EmbeddingsInfo{}, errors.New("embeddings info: response violates the gateway contract")
	}
	return EmbeddingsInfo{
		Provider:    w.Provider,
		Model:       w.Model,
		Dim:         w.Dim,
		Fingerprint: w.Fingerprint,
		Collection:  w.Collection,
		SparseModel: deref(w.SparseModel),
		Reranker:    EmbeddingsRerankerInfo{Provider: w.Reranker.Provider, Model: deref(w.Reranker.Model)},
		Egress:      EmbeddingsEgress{DenseHost: deref(w.Egress.DenseHost), RerankHost: deref(w.Egress.RerankHost)},
	}, nil
}

// Ready checks the gateway's model-aware readiness endpoint (GET /readyz). Once
// it passes and the profile is still unknown, it reads /v1/info (at most once
// per infoRetry). Only a rejected internal bearer fails readiness: it means
// every query would fail. An older gateway without /v1/info stays ready.
func (e *QueryEmbedder) Ready(ctx context.Context) error {
	serviceURL := strings.TrimSuffix(strings.TrimRight(e.baseURL, "/"), "/v1")
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, serviceURL+"/readyz", nil)
	if err != nil {
		return err
	}
	resp, err := e.http.Do(req)
	if err != nil {
		return err
	}
	_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 4<<10))
	_ = resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("embeddings ready: unexpected status %d", resp.StatusCode)
	}

	if e.info.Load() != nil {
		return nil
	}
	e.infoMu.Lock()
	defer e.infoMu.Unlock()
	err = e.infoErr
	if e.info.Load() == nil && (e.infoAttempt.IsZero() || time.Since(e.infoAttempt) >= e.infoRetry) {
		_, err = e.refreshInfoLocked(ctx)
	}
	if errors.Is(err, ErrEmbeddingsUnauthorized) {
		return err
	}
	return nil
}

// setBearer authenticates a gateway request with the internal API secret. An
// empty token sends no header (a local gateway with auth disabled).
func setBearer(req *http.Request, token string) {
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
}

// gatewayStatusError maps a non-200 gateway status to an error, singling out a
// rejected internal bearer so operators see the misconfiguration.
func gatewayStatusError(op string, status int) error {
	if status == http.StatusUnauthorized || status == http.StatusForbidden {
		return fmt.Errorf("%s: status %d: %w", op, status, ErrEmbeddingsUnauthorized)
	}
	return fmt.Errorf("%s: unexpected status %d", op, status)
}

var _ ports.QueryEmbedder = (*QueryEmbedder)(nil)
