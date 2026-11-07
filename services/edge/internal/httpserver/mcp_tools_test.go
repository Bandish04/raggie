// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"fmt"
	"slices"
	"testing"

	"github.com/alicangunduz/raggie/services/edge/internal/mcp"
	"github.com/alicangunduz/raggie/services/edge/internal/ports"
)

func rankedNames(defs []mcp.ToolDef) []string {
	out := make([]string, len(defs))
	for i, d := range defs {
		out[i] = d.Name
	}
	return out
}

// largeCatalog is 60 generic read tools with one distinctive, server-annotated
// read-only tool at index 50 (it must survive the read-only policy).
func largeCatalog() []mcp.ToolDef {
	defs := make([]mcp.ToolDef, 0, 60)
	for i := 0; i < 60; i++ {
		defs = append(defs, mcp.ToolDef{Name: fmt.Sprintf("crm_get_record_%02d", i), Description: "Read a CRM record"})
	}
	readOnly := true
	defs[50] = mcp.ToolDef{Name: "invoice_export_csv", Description: "Export invoices to a CSV file", ReadOnlyHint: &readOnly}
	return defs
}

// Relevance decides the rank, wherever the tool sits in provider order.
func TestRankMCPToolsSurfacesTheMatchFromDeepInTheCatalog(t *testing.T) {
	got := rankedNames(rankMCPTools(largeCatalog(), "export invoices", mcpSearchRevealLimit))
	if len(got) != mcpSearchRevealLimit || got[0] != "invoice_export_csv" {
		t.Fatalf("ranking = %v, want invoice_export_csv first", got)
	}
}

// Equal scores keep provider order; more matched terms rank higher.
func TestRankMCPToolsBreaksTiesByProviderOrder(t *testing.T) {
	defs := []mcp.ToolDef{
		{Name: "a_list", Description: "List things"},
		{Name: "b_search", Description: "Search issues"},
		{Name: "c_search", Description: "Search issues"},
		{Name: "d_search_issues_by_jql", Description: "Search issues with JQL"},
		{Name: "e_search", Description: "Search issues"},
	}
	got := rankedNames(rankMCPTools(defs, "search issues jql", 0))
	want := []string{"d_search_issues_by_jql", "b_search", "c_search", "e_search", "a_list"}
	if !slices.Equal(got, want) {
		t.Fatalf("ranking = %v, want %v", got, want)
	}
}

// A query matching nothing returns the first N tools in provider order.
func TestRankMCPToolsZeroMatchKeepsProviderOrder(t *testing.T) {
	got := rankedNames(rankMCPTools(largeCatalog(), "zzz-no-such-capability", 3))
	if want := []string{"crm_get_record_00", "crm_get_record_01", "crm_get_record_02"}; !slices.Equal(got, want) {
		t.Fatalf("ranking = %v, want %v", got, want)
	}
	if got := rankMCPTools(largeCatalog(), "", 0); len(got) != 60 || got[0].Name != "crm_get_record_00" {
		t.Fatalf("empty query: %d tools, first %q", len(got), got[0].Name)
	}
}

// End to end: the model asks search_tools for a capability buried deep in a
// large catalog and is offered that tool in the next step.
func TestSearchToolsRevealsTheRelevantToolToTheModel(t *testing.T) {
	for _, unified := range []bool{false, true} {
		chat := &scriptedChat{script: []ports.ChatChunk{toolCall("search_tools", `{"query":"export invoices to csv"}`)}}
		internalToolChat(t, mcpTestCfg(unified), &catalogTools{defs: largeCatalog()}, chat)
		if len(chat.reqs) < 2 {
			t.Fatalf("unified=%v: search_tools flow did not run (%d requests)", unified, len(chat.reqs))
		}
		if offered := chat.offered(); !offered["invoice_export_csv"] {
			t.Fatalf("unified=%v: invoice_export_csv was never offered after search_tools", unified)
		}
	}
}
