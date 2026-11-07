// SPDX-License-Identifier: Apache-2.0

package rag

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"log/slog"
	"strings"
	"testing"

	"github.com/alicangunduz/raggie/services/edge/internal/ports"
	"github.com/alicangunduz/raggie/services/edge/internal/ports/mock"
)

// recordingStore captures the query vectors it was searched with and returns a
// fixed result.
type recordingStore struct {
	got    ports.QueryVectors
	chunks []ports.Chunk
	err    error
}

func (s *recordingStore) Search(_ context.Context, _ []string, q ports.QueryVectors, _ int) ([]ports.Chunk, error) {
	s.got = q
	return s.chunks, s.err
}

func TestRetrieveSearchesTheGatewayCollection(t *testing.T) {
	store := &recordingStore{}
	s := New(mock.QueryEmbedder{Dim: 8, Collection: "raggie_chunks_d8_0a1b2c3d", Fingerprint: "0a1b2c3d"}, store)
	if _, err := s.Retrieve(context.Background(), []string{"ws"}, "q", 4, 2); err != nil {
		t.Fatal(err)
	}
	if store.got.Collection != "raggie_chunks_d8_0a1b2c3d" || store.got.Fingerprint != "0a1b2c3d" || len(store.got.Dense) != 8 {
		t.Fatalf("store searched with %+v", store.got)
	}
}

func TestRetrieveMissingCollectionIsEmptyNotAnError(t *testing.T) {
	var logs bytes.Buffer
	store := &recordingStore{err: fmt.Errorf("qdrant query raggie_chunks_d8: %w", ports.ErrCollectionMissing)}
	s := New(mock.QueryEmbedder{Dim: 8}, store, WithLogger(slog.New(slog.NewTextHandler(&logs, nil))))

	for i := 0; i < 3; i++ {
		res, err := s.Retrieve(context.Background(), []string{"ws"}, "q", 4, 2)
		if err != nil {
			t.Fatalf("a missing collection must not fail retrieval, got %v", err)
		}
		if len(res.Chunks) != 0 || res.ContextText != "" {
			t.Fatalf("expected an empty retrieval, got %+v", res)
		}
	}
	if n := strings.Count(logs.String(), "vector collection missing"); n != 1 {
		t.Fatalf("missing-collection warning logged %d times, want 1 (rate-limited): %s", n, logs.String())
	}
	if !strings.Contains(logs.String(), "level=WARN") {
		t.Fatalf("expected a warning, got: %s", logs.String())
	}
}

func TestRetrieveOtherStoreErrorsStillFail(t *testing.T) {
	boom := errors.New("qdrant down")
	s := New(mock.QueryEmbedder{Dim: 8}, &recordingStore{err: boom})
	if _, err := s.Retrieve(context.Background(), []string{"ws"}, "q", 4, 2); !errors.Is(err, boom) {
		t.Fatalf("err = %v, want the store error", err)
	}
}
