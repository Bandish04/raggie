// SPDX-License-Identifier: Apache-2.0

// Per-workspace chat-intelligence flags (PUT /admin/workspaces/{id}/settings).
// Each only takes effect while its global kill switch is on as well.

export const WORKSPACE_FLAGS = ["web_search_enabled", "personalization_enabled", "memory_enabled"] as const;

export type WorkspaceFlag = (typeof WORKSPACE_FLAGS)[number];

export const isWorkspaceFlag = (v: string): v is WorkspaceFlag =>
  (WORKSPACE_FLAGS as readonly string[]).includes(v);

/** A settings PUT body that changes exactly one flag. */
export function workspaceFlagBody(field: WorkspaceFlag, enabled: boolean): Partial<Record<WorkspaceFlag, boolean>> {
  return { [field]: enabled };
}
