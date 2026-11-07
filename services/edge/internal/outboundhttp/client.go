// SPDX-License-Identifier: Apache-2.0

// Package outboundhttp owns the shared transport used for trusted edge
// dependencies. Sharing one tuned transport avoids creating a fresh connection
// pool for every adapter while preserving per-client request timeouts.
package outboundhttp

import (
	"net"
	"net/http"
	"sync"
	"time"
)

// DefaultLLMResponseHeaderTimeout is the time an LLM endpoint gets to send its
// response headers (its first byte) when no other budget is configured.
const DefaultLLMResponseHeaderTimeout = 60 * time.Second

var sharedTransport = newTransport(DefaultLLMResponseHeaderTimeout)

// llmTransports holds one pool per distinct response-header timeout, so a
// slow model (CPU Ollama with long prompts) can be waited for without
// loosening the budget of every other dependency.
var (
	llmMu         sync.Mutex
	llmTransports = map[time.Duration]*http.Transport{}
)

// NewClient returns a client backed by the process-wide keep-alive pool.
// A zero timeout is intentional for streaming protocols whose lifetime is
// controlled by the request context.
func NewClient(timeout time.Duration) *http.Client {
	return &http.Client{
		Transport: sharedTransport,
		Timeout:   timeout,
	}
}

// NewLLMClient returns a client for an LLM endpoint whose transport waits up
// to headerTimeout for the response headers (<= 0 uses
// DefaultLLMResponseHeaderTimeout). Clients with the same header timeout share
// one keep-alive pool; timeout is the overall client timeout as in NewClient.
func NewLLMClient(timeout, headerTimeout time.Duration) *http.Client {
	if headerTimeout <= 0 {
		headerTimeout = DefaultLLMResponseHeaderTimeout
	}
	llmMu.Lock()
	tr, ok := llmTransports[headerTimeout]
	if !ok {
		tr = newTransport(headerTimeout)
		llmTransports[headerTimeout] = tr
	}
	llmMu.Unlock()
	return &http.Client{Transport: tr, Timeout: timeout}
}

// CloseIdleConnections releases pooled sockets during graceful shutdown.
func CloseIdleConnections() {
	sharedTransport.CloseIdleConnections()
	llmMu.Lock()
	defer llmMu.Unlock()
	for _, tr := range llmTransports {
		tr.CloseIdleConnections()
	}
}

func newTransport(responseHeaderTimeout time.Duration) *http.Transport {
	base := http.DefaultTransport.(*http.Transport).Clone()
	base.Proxy = http.ProxyFromEnvironment
	base.DialContext = (&net.Dialer{
		Timeout:   10 * time.Second,
		KeepAlive: 30 * time.Second,
	}).DialContext
	base.ForceAttemptHTTP2 = true
	base.MaxIdleConns = 1024
	base.MaxIdleConnsPerHost = 256
	base.MaxConnsPerHost = 512
	base.IdleConnTimeout = 90 * time.Second
	base.TLSHandshakeTimeout = 10 * time.Second
	base.ResponseHeaderTimeout = responseHeaderTimeout
	base.ExpectContinueTimeout = time.Second
	return base
}
