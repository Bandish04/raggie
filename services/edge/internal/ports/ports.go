// SPDX-License-Identifier: Apache-2.0

// Package ports defines the edge service's outbound interfaces (hexagonal
// "ports"). Concrete adapters — Qdrant, the OpenAI-compatible LLMaaS, Postgres,
// the event bus — live behind these so the RAG core never depends on a specific
// implementation (loose coupling is a hard design rule). Mocks in ports/mock
// back the tests.
package ports

import (
	"context"
	"encoding/json"
	"errors"
)

// SparseVector is a BM25 sparse vector: parallel arrays of token indices and
// weights, as produced by the embeddings service and consumed by Qdrant's named
// "bm25" sparse vector (IDF modifier applied server-side).
type SparseVector struct {
	Indices []uint32  `json:"indices"`
	Values  []float32 `json:"values"`
}

// QueryVectors is one embedded search query as returned by the embeddings
// gateway (POST /v1/query): the dense and sparse vectors plus the Qdrant
// collection holding vectors of the gateway's active embedding profile and that
// profile's fingerprint. Collection and Fingerprint are empty when an older
// gateway omits them; the vector store then derives the legacy collection from
// the dense dimension.
type QueryVectors struct {
	Dense       []float32
	Sparse      SparseVector
	Collection  string
	Fingerprint string
}

// QueryEmbedder returns both the dense and sparse representations of a query in
// one call, for hybrid (dense + sparse) retrieval. Sparse may be empty when the
// embeddings service has hybrid disabled — callers then fall back to dense-only.
type QueryEmbedder interface {
	EmbedQuery(ctx context.Context, query string) (QueryVectors, error)
}

// Chunk is a retrieved document fragment with its similarity score, used to
// assemble RAG context and to render answer citations (sources_json).
type Chunk struct {
	DocumentID string  `json:"document_id"`
	Filename   string  `json:"filename"`
	ChunkIndex int     `json:"chunk_index"`
	ChunkKind  string  `json:"chunk_kind,omitempty"`
	Section    string  `json:"section_path,omitempty"`
	Text       string  `json:"text"`
	Score      float32 `json:"score"`
}

// ErrCollectionMissing reports that the vector collection a query targets does
// not exist yet (nothing has been indexed under the active embedding profile,
// e.g. a fresh install or right after a profile switch). Retrieval treats it as
// "no documents", not as an upstream failure.
var ErrCollectionMissing = errors.New("vector collection does not exist")

// VectorStore performs workspace-filtered HYBRID search over chunks: dense +
// sparse candidates fused (RRF) server-side. workspaceIDs filters to any of the
// given workspaces (one for a single-workspace chat, many for "all workspaces").
// It searches q.Collection (falling back to the dimension-derived legacy name
// when empty); an empty sparse vector degrades to a dense-only search. A missing
// collection is reported as an error wrapping ErrCollectionMissing.
type VectorStore interface {
	Search(ctx context.Context, workspaceIDs []string, q QueryVectors, k int) ([]Chunk, error)
}

// Reranker re-scores candidate chunks by query–passage relevance (a cross-encoder
// hosted by the embeddings service). It returns the candidate indices in
// best-first order, each with its relevance score, optionally truncated to topN.
// Implementations MUST degrade gracefully: on any failure the caller keeps the
// dense similarity order, so retrieval never blocks on the reranker.
type Reranker interface {
	Rerank(ctx context.Context, query string, documents []string, topN int) ([]RerankHit, error)
}

// RerankHit is one reranked candidate: its original index in the input slice and
// its relevance score from the cross-encoder.
type RerankHit struct {
	Index int
	Score float32
}

// Role values for chat messages.
const (
	RoleSystem    = "system"
	RoleUser      = "user"
	RoleAssistant = "assistant"
	RoleTool      = "tool" // an MCP tool result fed back to the model (OpenAI tool role)
)

// ContentPart is one element of a multimodal message (OpenAI-compatible). Type is
// "text" or "image_url"; exactly one of Text / ImageURL is set.
type ContentPart struct {
	Type     string        `json:"type"`
	Text     string        `json:"text,omitempty"`
	ImageURL *ImageURLPart `json:"image_url,omitempty"`
}

// ImageURLPart carries an image as a data: URL (base64) or a remote URL.
type ImageURLPart struct {
	URL string `json:"url"`
}

// Message is a single chat turn. Content is a plain string for the common case;
// when Parts is non-empty the message serialises as an OpenAI multimodal content
// array instead (text + image_url parts), so vision requests need no other change.
//
// Two extra (optional) shapes support the MCP tool-calling loop, both OpenAI-wire:
//   - an ASSISTANT message that requested tools carries ToolCalls (and a null
//     content), emitted as {role:"assistant", content:null, tool_calls:[...]}.
//   - a TOOL message carries the result of one call via ToolCallID, emitted as
//     {role:"tool", tool_call_id:"...", content:"..."}.
//
// These fields are zero-valued on every normal turn, so the marshalling for the
// plain-string and multimodal cases is unchanged when they are unset.
type Message struct {
	Role       string        `json:"role"`
	Content    string        `json:"-"`
	Parts      []ContentPart `json:"-"`
	ToolCalls  []ToolCall    `json:"-"` // assistant turn that requested tool calls
	ToolCallID string        `json:"-"` // tool turn: which call this result answers
}

// MarshalJSON emits the OpenAI message wire form. Tool-calling shapes take
// precedence (they are only set on the in-memory messages the agentic loop
// appends); otherwise the original {role, content[/parts]} behaviour applies.
func (m Message) MarshalJSON() ([]byte, error) {
	switch {
	case m.Role == RoleTool:
		return json.Marshal(struct {
			Role       string `json:"role"`
			ToolCallID string `json:"tool_call_id"`
			Content    string `json:"content"`
		}{m.Role, m.ToolCallID, m.Content})
	case len(m.ToolCalls) > 0:
		// Assistant turn requesting tools: content is null per the OpenAI spec.
		calls := make([]wireToolCall, len(m.ToolCalls))
		for i, tc := range m.ToolCalls {
			calls[i] = wireToolCall{
				ID:   tc.ID,
				Type: "function",
				Function: wireToolCallFn{
					Name:      tc.Name,
					Arguments: tc.Arguments,
				},
			}
		}
		return json.Marshal(struct {
			Role      string         `json:"role"`
			Content   any            `json:"content"`
			ToolCalls []wireToolCall `json:"tool_calls"`
		}{m.Role, nil, calls})
	case len(m.Parts) == 0:
		return json.Marshal(struct {
			Role    string `json:"role"`
			Content string `json:"content"`
		}{m.Role, m.Content})
	default:
		return json.Marshal(struct {
			Role    string        `json:"role"`
			Content []ContentPart `json:"content"`
		}{m.Role, m.Parts})
	}
}

// UnmarshalJSON accepts a string content (the only form clients send as history).
func (m *Message) UnmarshalJSON(data []byte) error {
	var aux struct {
		Role    string `json:"role"`
		Content string `json:"content"`
	}
	if err := json.Unmarshal(data, &aux); err != nil {
		return err
	}
	m.Role, m.Content, m.Parts, m.ToolCalls, m.ToolCallID = aux.Role, aux.Content, nil, nil, ""
	return nil
}

// wireToolCall / wireToolCallFn are the OpenAI tool_calls wire shapes used when
// marshalling an assistant tool-request message.
type wireToolCall struct {
	ID       string         `json:"id"`
	Type     string         `json:"type"`
	Function wireToolCallFn `json:"function"`
}

type wireToolCallFn struct {
	Name      string `json:"name"`
	Arguments string `json:"arguments"` // raw JSON string, as the provider expects
}

// ToolSpec advertises one callable tool to the model (OpenAI function-tool form).
// Parameters is the raw JSON Schema for the tool's arguments, passed through
// verbatim from the MCP server's tool definition.
type ToolSpec struct {
	Name        string
	Description string
	Parameters  json.RawMessage
}

// ToolCall is one tool invocation the model asked for: a stable ID (echoed back
// on the matching tool result message), the tool Name, and its Arguments as a
// raw JSON string (reassembled from the streamed fragments).
type ToolCall struct {
	ID        string
	Name      string
	Arguments string
}

// ChatRequest is a completion request sent to the provider.
type ChatRequest struct {
	Model       string    `json:"model"`
	Messages    []Message `json:"messages"`
	Temperature float32   `json:"temperature"`
	MaxTokens   int       `json:"max_tokens,omitempty"`
	// ReasoningEffort tunes a reasoning model's chain-of-thought depth
	// ("low"|"medium"|"high"). Sent to the provider as "reasoning_effort" only
	// when non-empty; empty omits the key (provider default applies).
	ReasoningEffort string `json:"reasoning_effort,omitempty"`
	// Tools, when non-empty, advertises callable tools to the model and switches
	// the request into tool-calling mode ("tools" + "tool_choice"). Empty (the
	// default for every existing caller) sends NO tools field — the request is
	// byte-for-byte the legacy completion.
	Tools []ToolSpec `json:"-"`
	// ToolChoice overrides the tool-calling strategy when Tools is non-empty.
	// Empty defaults to "auto" (the model decides). "required" forces the model
	// to call at least one tool this turn (the semi-autonomous "if I toggled it,
	// it searched" guarantee). Ignored when Tools is empty.
	ToolChoice string `json:"-"`
}

// ChatChunk is a streamed delta from the chat provider. A chunk carries EITHER
// answer text (Delta) OR chain-of-thought text (Reasoning) — never both: the
// provider streams reasoning deltas first, then content deltas. When Done is
// true the stream is complete and Usage may be populated.
//
// In tool-calling mode the provider may instead finish a turn by requesting
// tools: the terminal chunk then carries the fully-assembled ToolCalls together
// with FinishReason=="tool_calls" and Done=true (the streamed argument fragments
// are reassembled by index inside the provider, so the handler sees one chunk).
// A transport/protocol failure is emitted once with Err set and Done=false.
type ChatChunk struct {
	Delta        string
	Reasoning    string
	Done         bool
	Err          error // terminal stream/protocol failure; Done is false
	Usage        *Usage
	ToolCalls    []ToolCall // populated only on a tool-calls terminal chunk
	FinishReason string     // e.g. "stop" | "tool_calls" (set on the terminal chunk)
}

// Usage reports token accounting for a completion (for the dashboard and
// messages.used_tokens).
type Usage struct {
	PromptTokens     int
	CompletionTokens int
}

// ChatProvider streams a chat completion token-by-token. The returned channel
// is closed when the stream ends or the context is cancelled.
type ChatProvider interface {
	Stream(ctx context.Context, req ChatRequest) (<-chan ChatChunk, error)
}

// ModelLister returns the chat model ids the provider exposes (its GET /models),
// for admin discovery of available models. Separate from ChatProvider so the hot
// path never depends on it.
type ModelLister interface {
	ListModels(ctx context.Context) ([]string, error)
}

// ModelDescriptor is non-secret runtime metadata for an explicitly-routed model.
// Available reflects the provider's live /models response at discovery time.
type ModelDescriptor struct {
	ID            string   `json:"id"`
	Provider      string   `json:"provider"`
	UpstreamModel string   `json:"upstream_model"`
	Capabilities  []string `json:"capabilities"`
	Available     bool     `json:"available"`
}

// ModelProfileLister exposes provider/capability metadata to the admin UI.
type ModelProfileLister interface {
	ListModelProfiles(ctx context.Context) ([]ModelDescriptor, error)
}

// WebResult is one web-search hit used to ground a web-augmented answer when the
// user's documents don't cover the question.
type WebResult struct {
	Title         string   `json:"title"`
	URL           string   `json:"url"`
	Snippet       string   `json:"snippet"`
	ExtraSnippets []string `json:"extra_snippets,omitempty"`
	Query         string   `json:"query,omitempty"`
	RetrievedAt   string   `json:"retrieved_at,omitempty"`
	Excerpt       string   `json:"excerpt,omitempty"`
	ReadStatus    string   `json:"read_status,omitempty"`
	Score         float32  `json:"score,omitempty"`
}

// WebSearcher performs a web search (e.g. Brave). Fail-open by contract: any
// error means the caller falls back to the documents-only path — it never blocks
// the chat. nil disables the feature entirely.
type WebSearcher interface {
	Search(ctx context.Context, query string, topN int) ([]WebResult, error)
}

// WebSearchOptions are provider-neutral knobs for one SERP request.
type WebSearchOptions struct {
	TopN          int
	Offset        int
	Freshness     string
	Country       string
	SearchLang    string
	UILang        string
	ResultFilter  string
	ExtraSnippets bool
}

// WebResearchOptions bound the richer SERP -> public-page-read -> evidence flow.
type WebResearchOptions struct {
	TopN             int
	MaxResults       int
	ReadEnabled      bool
	ReadTopN         int
	EvidenceTopK     int
	QueryConcurrency int
	FetchConcurrency int
	FetchTimeout     int
	MaxBodyBytes     int64
	Country          string
	SearchLang       string
	UILang           string
	Freshness        string
	ResultFilter     string
	ExtraSnippets    bool
	TotalTimeoutSecs int
}

// WebResearcher is an optional richer web adapter. Implementations still fail
// open: callers fall back to WebSearcher or documents-only on any error.
type WebResearcher interface {
	SearchWithOptions(ctx context.Context, query string, opts WebSearchOptions) ([]WebResult, bool, error)
	Research(ctx context.Context, question string, queries []string, opts WebResearchOptions) ([]WebResult, error)
}

// Workspace is the subset of workspace configuration the edge needs on the hot
// path.
type Workspace struct {
	ID           string
	Type         string // INTERNAL | EXTERNAL
	SystemPrompt string
	Temperature  float32
}

// Repository is the edge's read view of the relational system-of-record.
type Repository interface {
	GetWorkspace(ctx context.Context, id string) (Workspace, error)
}

// EventBus publishes domain events (e.g. "chat.completed" consumed by the
// auto-evaluator). The single-node impl is Redis Streams; prod is Redpanda.
type EventBus interface {
	Publish(ctx context.Context, topic string, payload []byte) error
}
