// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"

	"github.com/alicangunduz/raggie/services/edge/internal/agent"
	"github.com/alicangunduz/raggie/services/edge/internal/config"
	"github.com/alicangunduz/raggie/services/edge/internal/ports"
)

const (
	toolKindWeb  = "web_search"
	toolKindDeep = "deep_research"
	toolKindMCP  = "mcp"
)

var webSearchToolSchema = json.RawMessage(`{
  "type":"object",
  "properties":{"query":{"type":"string","description":"Focused web search query. Leave empty to let Raggie derive it from the user question."}},
  "additionalProperties":false
}`)

var deepResearchToolSchema = json.RawMessage(`{
  "type":"object",
  "properties":{"query":{"type":"string","description":"Research focus. Leave empty to research the user's original question."}},
  "additionalProperties":false
}`)

type toolSourceState struct {
	cards []map[string]any
	raw   []byte
}

func newToolSourceState(cards []map[string]any) *toolSourceState {
	s := &toolSourceState{cards: append([]map[string]any(nil), cards...)}
	s.refresh()
	return s
}

func (s *toolSourceState) refresh() {
	s.raw, _ = json.Marshal(s.cards)
}

func (s *toolSourceState) JSON() []byte {
	if s == nil {
		return []byte("[]")
	}
	return s.raw
}

func (s *toolSourceState) emit(emit agent.Emit) {
	if s == nil || emit == nil {
		return
	}
	emit("sources", []byte(fmt.Sprintf(`{"sources":%s}`, s.raw)))
}

func (s *toolSourceState) addWebResults(emit agent.Emit, results []ports.WebResult) string {
	if s == nil || len(results) == 0 {
		return ""
	}
	firstCitation := len(s.cards) + 1
	block := webEvidenceContextBlockFrom(results, firstCitation)
	s.cards = append(s.cards, webSourceCards(results)...)
	s.refresh()
	s.emit(emit)
	return block
}

func addWebResearchTools(
	reg *agent.Registry,
	deps Deps,
	logger *slog.Logger,
	cfg config.Config,
	req chatStreamRequest,
	sourceState *toolSourceState,
	emit agent.Emit,
	enableWeb, enableDeep bool,
) {
	if reg == nil {
		return
	}
	if enableWeb {
		reg.Add(agent.Tool{
			Kind: toolKindWeb,
			Spec: ports.ToolSpec{
				Name:        "web_search",
				Description: "Search and read public web results for current or recent information. Returns cited evidence blocks.",
				Parameters:  webSearchToolSchema,
			},
			Invoke: func(ic context.Context, argsJSON json.RawMessage) (string, bool, error) {
				query := webToolQuery(argsJSON)
				if query == "" {
					query = generateWebQuery(ic, deps, logger, req.Model, req.Message)
				}
				progress(searchProgressEmit(emit), "searching")
				progress(searchProgressEmit(emit), "reading")
				results := singleWebResearch(ic, deps, logger, cfg, req.Message, query)
				progress(searchProgressEmit(emit), "reranking")
				if len(results) == 0 {
					emit("web_unavailable", []byte("{}"))
					return "No usable web results were found for this query.", false, nil
				}
				block := sourceState.addWebResults(emit, results)
				return "Web search evidence. Cite these labels exactly in the final answer:\n\n" + block, false, nil
			},
		})
	}
	if enableDeep {
		reg.Add(agent.Tool{
			Kind: toolKindDeep,
			Spec: ports.ToolSpec{
				Name:        "deep_research",
				Description: "Run multi-query deep web research and return cited evidence blocks for a thorough answer.",
				Parameters:  deepResearchToolSchema,
			},
			Invoke: func(ic context.Context, argsJSON json.RawMessage) (string, bool, error) {
				question := webToolQuery(argsJSON)
				if question == "" {
					question = req.Message
				}
				emit("deep_progress", mustJSON(map[string]string{"status": "generating_queries"}))
				_, results := deepWebResearch(ic, deps, logger, cfg, req.Model, question, searchProgressEmit(emit))
				if len(results) == 0 {
					emit("web_unavailable", []byte("{}"))
					return "No usable deep research results were found for this query.", false, nil
				}
				block := sourceState.addWebResults(emit, results)
				return "Deep research evidence. Cite these labels exactly in the final answer:\n\n" + block, false, nil
			},
		})
	}
}

func webToolQuery(argsJSON json.RawMessage) string {
	var args struct {
		Query string `json:"query"`
	}
	_ = json.Unmarshal(argsJSON, &args)
	return cleanSingleWebQuery(args.Query)
}
