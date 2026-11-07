// SPDX-License-Identifier: Apache-2.0

package outboundhttp

import (
	"net/http"
	"testing"
	"time"
)

func TestClientsShareTunedTransport(t *testing.T) {
	stream := NewClient(0)
	bounded := NewClient(8 * time.Second)

	if stream.Timeout != 0 {
		t.Fatalf("streaming client must not have an overall timeout, got %s", stream.Timeout)
	}
	if bounded.Timeout != 8*time.Second {
		t.Fatalf("bounded client timeout = %s, want 8s", bounded.Timeout)
	}
	if stream.Transport != bounded.Transport {
		t.Fatal("clients must share one connection pool")
	}

	transport, ok := stream.Transport.(*http.Transport)
	if !ok {
		t.Fatalf("transport type = %T, want *http.Transport", stream.Transport)
	}
	if !transport.ForceAttemptHTTP2 {
		t.Fatal("HTTP/2 must be enabled")
	}
	if transport.MaxIdleConns != 1024 || transport.MaxIdleConnsPerHost != 256 {
		t.Fatalf(
			"unexpected idle pool sizing: total=%d per_host=%d",
			transport.MaxIdleConns,
			transport.MaxIdleConnsPerHost,
		)
	}
	if transport.MaxConnsPerHost != 512 {
		t.Fatalf("MaxConnsPerHost = %d, want 512", transport.MaxConnsPerHost)
	}
	if transport.ResponseHeaderTimeout != 60*time.Second {
		t.Fatalf("ResponseHeaderTimeout = %s, want 60s", transport.ResponseHeaderTimeout)
	}
}

// LLM clients get their own transports so a slow model's first byte (CPU
// Ollama, long prompts) can be waited for without loosening the budget of
// every other dependency. One pool per distinct header timeout.
func TestLLMClientsUseTheirOwnHeaderTimeout(t *testing.T) {
	headerTimeout := func(c *http.Client) time.Duration {
		t.Helper()
		tr, ok := c.Transport.(*http.Transport)
		if !ok {
			t.Fatalf("transport type = %T", c.Transport)
		}
		return tr.ResponseHeaderTimeout
	}
	slow := NewLLMClient(0, 300*time.Second)
	slowAdmin := NewLLMClient(10*time.Second, 300*time.Second)
	other := NewLLMClient(0, 90*time.Second)

	if got := headerTimeout(slow); got != 300*time.Second {
		t.Fatalf("LLM header timeout = %s, want 300s", got)
	}
	if slow.Transport != slowAdmin.Transport {
		t.Fatal("LLM clients with the same header timeout must share one pool")
	}
	if slow.Transport == other.Transport {
		t.Fatal("a different header timeout needs its own transport")
	}
	if slowAdmin.Timeout != 10*time.Second || slow.Timeout != 0 {
		t.Fatalf("client timeouts = %s/%s", slowAdmin.Timeout, slow.Timeout)
	}
	if shared := NewClient(0); shared.Transport == slow.Transport || headerTimeout(shared) != 60*time.Second {
		t.Fatalf("the shared non-LLM transport must keep its 60s header timeout, got %s", headerTimeout(shared))
	}
	if got := headerTimeout(NewLLMClient(0, 0)); got != DefaultLLMResponseHeaderTimeout {
		t.Fatalf("zero header timeout = %s, want the %s default", got, DefaultLLMResponseHeaderTimeout)
	}
	if tr := slow.Transport.(*http.Transport); tr.MaxConnsPerHost != 512 || !tr.ForceAttemptHTTP2 {
		t.Fatal("LLM transports must keep the shared pool tuning")
	}
}
