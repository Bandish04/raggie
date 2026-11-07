// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"context"
	"sync"
	"testing"

	"github.com/alicangunduz/raggie/services/edge/internal/ports"
)

type modelRecordingChatProvider struct {
	mu       sync.Mutex
	response string
	requests []ports.ChatRequest
}

func (p *modelRecordingChatProvider) Stream(
	ctx context.Context,
	req ports.ChatRequest,
) (<-chan ports.ChatChunk, error) {
	p.mu.Lock()
	p.requests = append(p.requests, req)
	p.mu.Unlock()
	ch := make(chan ports.ChatChunk, 2)
	ch <- ports.ChatChunk{Delta: p.response}
	ch <- ports.ChatChunk{Done: true}
	close(ch)
	return ch, nil
}

func (p *modelRecordingChatProvider) models() []string {
	p.mu.Lock()
	defer p.mu.Unlock()
	out := make([]string, len(p.requests))
	for i, request := range p.requests {
		out[i] = request.Model
	}
	return out
}

func TestWebResearchAuxiliaryCallsUseSelectedCanonicalModel(t *testing.T) {
	chat := &modelRecordingChatProvider{
		response: `{"queries":["enterprise rag"],"country":"TR","search_lang":"tr"}`,
	}
	deps := Deps{Chat: chat}

	query := generateWebQuery(context.Background(), deps, nil, "local-private", "RAG nedir?")
	if query == "" {
		t.Fatal("web query should not be empty")
	}
	plan := generateSearchPlan(
		context.Background(),
		deps,
		nil,
		"local-private",
		"Enterprise RAG araştır",
		4,
		"TR",
		"tr",
	)
	if len(plan.Queries) == 0 {
		t.Fatal("search plan should not be empty")
	}
	followups := generateFollowupQueries(
		context.Background(),
		deps,
		nil,
		"local-private",
		"Enterprise RAG araştır",
		[]ports.WebResult{{
			Title: "Source", URL: "https://example.test", Snippet: "Evidence",
		}},
		2,
	)
	if len(followups) == 0 {
		t.Fatal("follow-up query should not be empty")
	}

	for i, model := range chat.models() {
		if model != "local-private" {
			t.Fatalf("auxiliary call %d escaped selected model: %q", i, model)
		}
	}
}
