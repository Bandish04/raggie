// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"context"
	"encoding/json"
	"fmt"
	"sort"
	"strings"

	"github.com/alicangunduz/raggie/services/edge/internal/agent"
	"github.com/alicangunduz/raggie/services/edge/internal/mcp"
	"github.com/alicangunduz/raggie/services/edge/internal/ports"
)

const (
	mcpDirectCatalogLimit = 48
	mcpSearchRevealLimit  = 12
)

var reservedToolNames = map[string]bool{
	"web_search":    true,
	"deep_research": true,
	"search_tools":  true,
}

var searchToolsSchema = json.RawMessage(`{
  "type":"object",
  "properties":{"query":{"type":"string","description":"Capability or task to find relevant MCP tools for."}},
  "required":["query"]
}`)

// addMCPTools registers the provider's tools that pass the skill allow-list
// and, unless allowWrite (MCP_ALLOW_WRITE_TOOLS), the read-only policy.
func addMCPTools(reg *agent.Registry, provider mcp.ToolProvider, defs []mcp.ToolDef, allowList []string, allowWrite bool, userQuery string) {
	allowedDefs := filterAllowedMCPTools(defs, allowList, allowWrite)
	addOne := func(d mcp.ToolDef) {
		name := d.Name
		reg.Add(agent.Tool{
			Kind: toolKindMCP,
			Spec: ports.ToolSpec{Name: d.Name, Description: d.Description, Parameters: d.InputSchema},
			Invoke: func(ic context.Context, argsJSON json.RawMessage) (string, bool, error) {
				return provider.CallTool(ic, name, argsJSON)
			},
		})
	}
	if len(allowedDefs) <= mcpDirectCatalogLimit {
		for _, d := range allowedDefs {
			addOne(d)
		}
		return
	}

	for _, d := range rankMCPTools(allowedDefs, userQuery, mcpSearchRevealLimit) {
		addOne(d)
	}
	reg.Add(agent.Tool{
		Kind: "mcp_catalog",
		Spec: ports.ToolSpec{
			Name:        "search_tools",
			Description: "Search the connected MCP tool catalog by capability. Use this when the visible tools do not cover the task.",
			Parameters:  searchToolsSchema,
		},
		Invoke: func(_ context.Context, argsJSON json.RawMessage) (string, bool, error) {
			var args struct {
				Query string `json:"query"`
			}
			_ = json.Unmarshal(argsJSON, &args)
			matches := rankMCPTools(allowedDefs, args.Query, mcpSearchRevealLimit)
			if len(matches) == 0 {
				return "No matching MCP tools found.", false, nil
			}
			var b strings.Builder
			b.WriteString("Matching MCP tools now available in the next tool-calling step:\n")
			for _, d := range matches {
				addOne(d)
				fmt.Fprintf(&b, "- %s: %s\n", d.Name, d.Description)
			}
			return strings.TrimSpace(b.String()), false, nil
		},
	})
}

func filterAllowedMCPTools(defs []mcp.ToolDef, allowList []string, allowWrite bool) []mcp.ToolDef {
	out := make([]mcp.ToolDef, 0, len(defs))
	for _, d := range defs {
		if d.Name == "" {
			continue
		}
		if reservedToolNames[d.Name] {
			continue
		}
		if !allowWrite && !d.IsReadOnly() {
			continue
		}
		if allowed(allowList, "mcp") || allowed(allowList, d.Name) {
			out = append(out, d)
		}
	}
	return out
}

// rankMCPTools orders tools by how many query terms their name/description
// contain (most first) and returns at most limit of them. Equal scores —
// including a query that matches nothing — keep the provider's order.
func rankMCPTools(defs []mcp.ToolDef, query string, limit int) []mcp.ToolDef {
	if limit <= 0 || limit > len(defs) {
		limit = len(defs)
	}
	terms := strings.Fields(strings.ToLower(query))
	type scored struct {
		def   mcp.ToolDef
		score int
	}
	scoredDefs := make([]scored, 0, len(defs))
	for _, d := range defs {
		haystack := strings.ToLower(d.Name + " " + d.Description)
		score := 0
		for _, term := range terms {
			term = strings.Trim(term, ".,;:!?()[]{}\"'`")
			if term != "" && strings.Contains(haystack, term) {
				score++
			}
		}
		scoredDefs = append(scoredDefs, scored{def: d, score: score})
	}
	sort.SliceStable(scoredDefs, func(i, j int) bool { return scoredDefs[i].score > scoredDefs[j].score })
	out := make([]mcp.ToolDef, 0, limit)
	for _, s := range scoredDefs[:limit] {
		out = append(out, s.def)
	}
	return out
}
