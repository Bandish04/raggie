// SPDX-License-Identifier: Apache-2.0

// Package mock provides deterministic in-memory implementations of the edge
// ports for tests and local development (no external services required).
package mock

import (
	"context"
	"crypto/sha256"
	"strings"
	"sync"

	"github.com/alicangunduz/raggie/services/edge/internal/ports"
)

// QueryEmbedder produces a deterministic dense vector from the query's SHA-256
// hash (the same text always yields the same vector — stable tests, no network)
// plus a small fixed sparse vector, for hybrid-retrieval tests. Collection and
// Fingerprint are passed through verbatim (empty = an older gateway).
type QueryEmbedder struct {
	Dim         int
	Collection  string
	Fingerprint string
}

func (m QueryEmbedder) EmbedQuery(_ context.Context, query string) (ports.QueryVectors, error) {
	dim := m.Dim
	if dim <= 0 {
		dim = 8
	}
	h := sha256.Sum256([]byte(query))
	v := make([]float32, dim)
	for j := 0; j < dim; j++ {
		v[j] = float32(h[j%len(h)]) / 255.0
	}
	return ports.QueryVectors{
		Dense:       v,
		Sparse:      ports.SparseVector{Indices: []uint32{1, 2, 3}, Values: []float32{1, 1, 1}},
		Collection:  m.Collection,
		Fingerprint: m.Fingerprint,
	}, nil
}

// VectorStore returns a fixed set of chunks regardless of the query vectors.
type VectorStore struct {
	Chunks []ports.Chunk
}

func (m VectorStore) Search(_ context.Context, _ []string, _ ports.QueryVectors, k int) ([]ports.Chunk, error) {
	if k > 0 && k < len(m.Chunks) {
		return m.Chunks[:k], nil
	}
	return m.Chunks, nil
}

// ChatProvider streams a canned response word-by-word, honoring cancellation.
type ChatProvider struct {
	Response string
}

func (m ChatProvider) Stream(ctx context.Context, _ ports.ChatRequest) (<-chan ports.ChatChunk, error) {
	resp := m.Response
	if resp == "" {
		resp = "This is a mock response."
	}
	ch := make(chan ports.ChatChunk)
	go func() {
		defer close(ch)
		words := strings.Fields(resp)
		for _, w := range words {
			select {
			case <-ctx.Done():
				return
			case ch <- ports.ChatChunk{Delta: w + " "}:
			}
		}
		ch <- ports.ChatChunk{Done: true, Usage: &ports.Usage{PromptTokens: 0, CompletionTokens: len(words)}}
	}()
	return ch, nil
}

// WebSearcher returns canned results and records every query it is asked for, so
// tests can assert the deep-research path searched each sub-query SEQUENTIALLY.
// Results may key off the query (per-query map) or fall back to Default. An empty
// match (no map entry, no Default) returns no results, exercising the "0 results"
// fallback. Err (when set) makes every call fail.
type WebSearcher struct {
	mu      sync.Mutex
	Queries []string                     // recorded in call order
	Results map[string][]ports.WebResult // per-query canned results
	Default []ports.WebResult            // used when a query has no map entry
	Err     error                        // when set, every Search fails
}

func (m *WebSearcher) Search(_ context.Context, query string, _ int) ([]ports.WebResult, error) {
	m.mu.Lock()
	m.Queries = append(m.Queries, query)
	m.mu.Unlock()
	if m.Err != nil {
		return nil, m.Err
	}
	if r, ok := m.Results[query]; ok {
		return r, nil
	}
	return m.Default, nil
}

// AskedQueries returns a copy of the recorded queries (call order).
func (m *WebSearcher) AskedQueries() []string {
	m.mu.Lock()
	defer m.mu.Unlock()
	out := make([]string, len(m.Queries))
	copy(out, m.Queries)
	return out
}

// Repository serves a single canned workspace.
type Repository struct {
	Workspace ports.Workspace
}

func (m Repository) GetWorkspace(_ context.Context, _ string) (ports.Workspace, error) {
	return m.Workspace, nil
}

// EventBus records every published event in memory.
type EventBus struct {
	mu        sync.Mutex
	Published []Event
}

// Event is a captured publish call.
type Event struct {
	Topic   string
	Payload []byte
}

func (m *EventBus) Publish(_ context.Context, topic string, payload []byte) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.Published = append(m.Published, Event{Topic: topic, Payload: payload})
	return nil
}

// Events returns a copy of the recorded events.
func (m *EventBus) Events() []Event {
	m.mu.Lock()
	defer m.mu.Unlock()
	out := make([]Event, len(m.Published))
	copy(out, m.Published)
	return out
}

// Compile-time assertions that the mocks satisfy the ports.
var (
	_ ports.QueryEmbedder = QueryEmbedder{}
	_ ports.VectorStore   = VectorStore{}
	_ ports.ChatProvider  = ChatProvider{}
	_ ports.Repository    = Repository{}
	_ ports.EventBus      = (*EventBus)(nil)
	_ ports.WebSearcher   = (*WebSearcher)(nil)
)
