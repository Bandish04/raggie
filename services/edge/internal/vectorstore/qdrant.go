// SPDX-License-Identifier: Apache-2.0

package vectorstore

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"github.com/alicangunduz/raggie/services/edge/internal/outboundhttp"
	"github.com/alicangunduz/raggie/services/edge/internal/ports"
)

// QdrantStore performs workspace-filtered similarity search against Qdrant over
// its REST API (stdlib only — keeps the edge dependency-free; gRPC is a possible
// later optimization). Implements ports.VectorStore.
//
// The collection is the one the embeddings gateway named for the query (the
// active embedding profile's collection, the same one the ingester writes to);
// only when an older gateway omits it is it derived from the vector dimension.
type QdrantStore struct {
	baseURL string
	apiKey  string
	http    *http.Client
}

func NewQdrantStore(baseURL string) *QdrantStore {
	return &QdrantStore{
		baseURL: baseURL,
		http:    outboundhttp.NewClient(5 * time.Second),
	}
}

// WithAPIKey sets the key sent as the `api-key` header on every request
// (Qdrant service.api_key). An empty key sends no header.
func (q *QdrantStore) WithAPIKey(key string) *QdrantStore {
	q.apiKey = key
	return q
}

func (q *QdrantStore) authorize(req *http.Request) {
	if q.apiKey != "" {
		req.Header.Set("api-key", q.apiKey)
	}
}

// matchAny matches a keyword field against ANY of the given values (Qdrant
// `match: { any: [...] }`). Works for one workspace or many (the "all" view).
type matchAny struct {
	Any []string `json:"any"`
}

type fieldCondition struct {
	Key   string   `json:"key"`
	Match matchAny `json:"match"`
}

type qdrantFilter struct {
	Must []fieldCondition `json:"must"`
}

type searchParams struct {
	// HnswEf raises the HNSW search beam for higher recall (Qdrant default is 128
	// only for build-time; the query-time beam defaults lower). Costs a little
	// latency, still well inside the A2 budget for k in the tens.
	HnswEf int `json:"hnsw_ef,omitempty"`
}

// sparseQuery is the Qdrant sparse-vector query shape ({indices, values}).
type sparseQuery struct {
	Indices []uint32  `json:"indices"`
	Values  []float32 `json:"values"`
}

// prefetch is one branch of a hybrid query (named dense or sparse vector). Query
// is either a []float32 (dense) or a sparseQuery (sparse).
type prefetch struct {
	Query  any           `json:"query"`
	Using  string        `json:"using"`
	Limit  int           `json:"limit"`
	Params *searchParams `json:"params,omitempty"`
}

type fusion struct {
	Fusion string `json:"fusion"`
}

// queryRequest serves both shapes the edge issues:
//   - hybrid: Prefetch (dense + sparse) + Query={fusion:"rrf"} (Qdrant >= 1.10)
//   - dense-only fallback: Query=[]float32 + Using="dense" (sparse unavailable)
//
// The top-level Filter propagates to all prefetches (workspace isolation).
type queryRequest struct {
	Prefetch    []prefetch    `json:"prefetch,omitempty"`
	Query       any           `json:"query"`
	Using       string        `json:"using,omitempty"`
	Filter      *qdrantFilter `json:"filter,omitempty"`
	Params      *searchParams `json:"params,omitempty"`
	Limit       int           `json:"limit"`
	WithPayload bool          `json:"with_payload"`
}

// Named-vector keys — MUST match the ingester's collection schema.
const (
	denseVector  = "dense"
	sparseVector = "bm25"
)

// defaultHnswEf is the query-time HNSW beam width. Higher = better recall at a
// small latency cost; 128 is a safe recall-first default for this workload.
const defaultHnswEf = 128

type queryResponse struct {
	Result struct {
		Points []struct {
			Score   float32        `json:"score"`
			Payload map[string]any `json:"payload"`
		} `json:"points"`
	} `json:"result"`
}

func (q *QdrantStore) Search(ctx context.Context, workspaceIDs []string, qv ports.QueryVectors, k int) ([]ports.Chunk, error) {
	dense, sparse := qv.Dense, qv.Sparse
	collection := qv.Collection
	if collection == "" {
		collection = CollectionName(len(dense)) // older gateway: legacy naming
	}
	if !ValidCollectionName(collection) {
		return nil, fmt.Errorf("qdrant query: invalid collection name %q", collection)
	}
	// Tenant isolation is this filter: never send a search whose workspace set
	// is empty or has a blank id (a nil slice would even marshal to "any": null).
	if len(workspaceIDs) == 0 {
		return nil, errors.New("qdrant query: refusing a search without a workspace filter")
	}
	for _, id := range workspaceIDs {
		if strings.TrimSpace(id) == "" {
			return nil, errors.New("qdrant query: refusing a search with a blank workspace id")
		}
	}
	filter := &qdrantFilter{
		Must: []fieldCondition{{Key: "workspace_id", Match: matchAny{Any: workspaceIDs}}},
	}

	var body queryRequest
	if len(sparse.Indices) > 0 {
		// Hybrid: dense + sparse candidates fused with Reciprocal Rank Fusion.
		// The top-level filter propagates to both prefetches.
		body = queryRequest{
			Prefetch: []prefetch{
				{Query: dense, Using: denseVector, Limit: k, Params: &searchParams{HnswEf: defaultHnswEf}},
				{Query: sparseQuery{Indices: sparse.Indices, Values: sparse.Values}, Using: sparseVector, Limit: k},
			},
			Query:       fusion{Fusion: "rrf"},
			Filter:      filter,
			Limit:       k,
			WithPayload: true,
		}
	} else {
		// Dense-only fallback (sparse unavailable): query the named "dense" vector.
		body = queryRequest{
			Query:       dense,
			Using:       denseVector,
			Filter:      filter,
			Params:      &searchParams{HnswEf: defaultHnswEf},
			Limit:       k,
			WithPayload: true,
		}
	}

	reqBody, _ := json.Marshal(body)
	url := fmt.Sprintf("%s/collections/%s/points/query", q.baseURL, collection)
	// #nosec G704 -- baseURL is operator configuration (QDRANT_URL), never request input.
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(reqBody))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	q.authorize(req)

	resp, err := q.http.Do(req) // #nosec G704 -- operator-configured Qdrant endpoint (see above)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode == http.StatusNotFound {
		// The path is fixed, so a 404 can only mean the collection is absent.
		_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 4<<10))
		return nil, fmt.Errorf("qdrant query %s: %w", collection, ports.ErrCollectionMissing)
	}
	if resp.StatusCode != http.StatusOK {
		_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 4<<10))
		return nil, fmt.Errorf("qdrant query: unexpected status %d", resp.StatusCode)
	}

	var qr queryResponse
	if err := json.NewDecoder(resp.Body).Decode(&qr); err != nil {
		return nil, err
	}
	_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 4<<10))
	chunks := make([]ports.Chunk, 0, len(qr.Result.Points))
	for _, p := range qr.Result.Points {
		chunks = append(chunks, ports.Chunk{
			DocumentID: payloadString(p.Payload, "document_id"),
			Filename:   payloadString(p.Payload, "filename"),
			ChunkIndex: payloadInt(p.Payload, "chunk_index"),
			ChunkKind:  payloadString(p.Payload, "chunk_kind"),
			Section:    payloadString(p.Payload, "section_path"),
			Text:       payloadString(p.Payload, "text"),
			Score:      p.Score,
		})
	}
	return chunks, nil
}

func payloadString(payload map[string]any, key string) string {
	if v, ok := payload[key].(string); ok {
		return v
	}
	return ""
}

func payloadInt(payload map[string]any, key string) int {
	switch value := payload[key].(type) {
	case float64:
		return int(value)
	case int:
		return value
	case json.Number:
		n, _ := value.Int64()
		return int(n)
	default:
		return 0
	}
}

// Ready checks Qdrant's process readiness endpoint.
func (q *QdrantStore) Ready(ctx context.Context) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, q.baseURL+"/readyz", nil)
	if err != nil {
		return err
	}
	q.authorize(req)
	resp, err := q.http.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("qdrant ready: unexpected status %d", resp.StatusCode)
	}
	return nil
}

var _ ports.VectorStore = (*QdrantStore)(nil)
