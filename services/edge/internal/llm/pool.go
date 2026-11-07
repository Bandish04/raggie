// SPDX-License-Identifier: Apache-2.0

// Package llm holds the outbound clients of the edge: the OpenAI-compatible
// chat LLMaaS and the embeddings gateway (query embedding + rerank), each behind
// a bounded outbound pool.
package llm

import "errors"

// ErrUpstreamBusy is returned when the bounded outbound pool is at capacity; the
// edge sheds (HTTP 503 + Retry-After) rather than fanning unboundedly into the
// shared LLMaaS upstream — the true A5 ceiling (ARCHITECTURE §6.4).
var ErrUpstreamBusy = errors.New("llm upstream pool at capacity")

// pool is a counting semaphore bounding concurrent upstream calls.
type pool struct {
	sem chan struct{}
}

func newPool(n int) *pool {
	if n <= 0 {
		n = 1
	}
	return &pool{sem: make(chan struct{}, n)}
}

// tryAcquire takes a slot without blocking; false means the pool is full.
func (p *pool) tryAcquire() bool {
	select {
	case p.sem <- struct{}{}:
		return true
	default:
		return false
	}
}

func (p *pool) release() { <-p.sem }
