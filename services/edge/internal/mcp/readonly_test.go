// SPDX-License-Identifier: Apache-2.0

package mcp

import "testing"

// Unannotated tools are read-only only when their first verb is a read verb
// and nothing else in the name can write: no write verb, no "and"/"or"/"then"
// chaining a second action, no arbitrary-execution marker. Explicit
// annotations always win, and a destructive hint is never read-only.
func TestIsReadOnlyHeuristic(t *testing.T) {
	yes, no := true, false
	cases := []struct {
		def  ToolDef
		want bool
	}{
		// Plain readers, with and without a service prefix.
		{ToolDef{Name: "jira_get_issue"}, true},
		{ToolDef{Name: "jira_search"}, true},
		{ToolDef{Name: "confluence.search"}, true},
		{ToolDef{Name: "jira_batch_get_changelogs"}, true},
		{ToolDef{Name: "list-projects"}, true},
		{ToolDef{Name: "crm_get_record_07"}, true},
		// Adversarial names that used to pass.
		{ToolDef{Name: "sql_query"}, false},
		{ToolDef{Name: "db_query"}, false},      // "query" may mutate: not a read verb
		{ToolDef{Name: "graphql_query"}, false}, // ditto
		{ToolDef{Name: "search_and_replace"}, false},
		{ToolDef{Name: "get_or_insert"}, false},
		{ToolDef{Name: "list_and_purge"}, false},
		{ToolDef{Name: "describe_terminate_instance"}, false},
		{ToolDef{Name: "get_then_nuke"}, false},
		{ToolDef{Name: "find_and_frobnicate"}, false},
		{ToolDef{Name: "show_exec_command"}, false},
		{ToolDef{Name: "list_drop_table"}, false},
		{ToolDef{Name: "get_reset_password"}, false},
		{ToolDef{Name: "view_mark_read"}, false},
		{ToolDef{Name: "fetch_publish"}, false},
		{ToolDef{Name: "get_upsert_user"}, false},
		{ToolDef{Name: "lookup_revoke_token"}, false},
		{ToolDef{Name: "read_save_draft"}, false},
		{ToolDef{Name: "list_cancel_order"}, false},
		{ToolDef{Name: "get_submit_form"}, false},
		{ToolDef{Name: "get_grant_role"}, false},
		{ToolDef{Name: "get_modify_settings"}, false},
		{ToolDef{Name: "list_comment"}, false},
		// First verb must be a read verb; no verb at all is not read-only.
		{ToolDef{Name: "create_then_get"}, false},
		{ToolDef{Name: "do_something"}, false},
		{ToolDef{Name: ""}, false},
		// Annotations win over the name.
		{ToolDef{Name: "export_invoices", ReadOnlyHint: &yes}, true},
		{ToolDef{Name: "jira_get_issue", ReadOnlyHint: &no}, false},
		{ToolDef{Name: "jira_get_issue", DestructiveHint: &yes}, false},
		{ToolDef{Name: "export_invoices", ReadOnlyHint: &yes, DestructiveHint: &yes}, false},
	}
	for _, tc := range cases {
		if got := tc.def.IsReadOnly(); got != tc.want {
			t.Errorf("IsReadOnly(%q, ro=%v, destr=%v) = %v, want %v",
				tc.def.Name, ptr(tc.def.ReadOnlyHint), ptr(tc.def.DestructiveHint), got, tc.want)
		}
	}
}

func ptr(b *bool) any {
	if b == nil {
		return nil
	}
	return *b
}
