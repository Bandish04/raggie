// SPDX-License-Identifier: Apache-2.0

package mock

import (
	"context"
	"testing"

	"github.com/alicangunduz/raggie/services/edge/internal/ports"
)

func TestQueryEmbedderDeterministicAndSized(t *testing.T) {
	e := QueryEmbedder{Dim: 16, Collection: "raggie_chunks_d16_0a1b2c3d", Fingerprint: "0a1b2c3d"}
	a, err := e.EmbedQuery(context.Background(), "hello")
	if err != nil {
		t.Fatal(err)
	}
	b, _ := e.EmbedQuery(context.Background(), "hello")
	if len(a.Dense) != 16 {
		t.Fatalf("expected dim 16, got %d", len(a.Dense))
	}
	for i := range a.Dense {
		if a.Dense[i] != b.Dense[i] {
			t.Fatal("embedding is not deterministic")
		}
	}
	if a.Collection != "raggie_chunks_d16_0a1b2c3d" || a.Fingerprint != "0a1b2c3d" || len(a.Sparse.Indices) == 0 {
		t.Fatalf("unexpected query vectors: %+v", a)
	}
}

func TestChatProviderStreamsAndCompletes(t *testing.T) {
	p := ChatProvider{Response: "alpha beta gamma"}
	ch, err := p.Stream(context.Background(), ports.ChatRequest{})
	if err != nil {
		t.Fatal(err)
	}
	var got string
	var done bool
	for c := range ch {
		if c.Done {
			done = true
			continue
		}
		got += c.Delta
	}
	if !done {
		t.Fatal("stream never signalled Done")
	}
	if got != "alpha beta gamma " {
		t.Fatalf("unexpected stream output: %q", got)
	}
}

func TestVectorStoreRespectsK(t *testing.T) {
	vs := VectorStore{Chunks: []ports.Chunk{{Text: "a"}, {Text: "b"}, {Text: "c"}, {Text: "d"}, {Text: "e"}}}
	out, _ := vs.Search(context.Background(), []string{"ws"}, ports.QueryVectors{}, 4)
	if len(out) != 4 {
		t.Fatalf("expected 4 chunks, got %d", len(out))
	}
}

func TestEventBusRecords(t *testing.T) {
	var bus EventBus
	_ = bus.Publish(context.Background(), "chat.completed", []byte(`{"id":"1"}`))
	if events := bus.Events(); len(events) != 1 || events[0].Topic != "chat.completed" {
		t.Fatalf("expected 1 chat.completed event, got %#v", bus.Events())
	}
}
