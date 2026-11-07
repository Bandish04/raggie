// SPDX-License-Identifier: Apache-2.0

"use server";

import { revalidatePath } from "next/cache";

import { createWorkspace, me, updateWidgetOrigins, updateWorkspaceSettings } from "@/lib/api";
import { getFreshAccessToken } from "@/lib/session";
import { normalizeOrigin } from "@/lib/widget-origins";
import { isWorkspaceFlag, workspaceFlagBody, type WorkspaceFlag } from "@/lib/workspace-flags";

export type WorkspaceActionState = { ok?: boolean; error?: boolean };

export async function createWorkspaceAction(
  _prev: WorkspaceActionState,
  form: FormData,
): Promise<WorkspaceActionState> {
  const token = await getFreshAccessToken();
  if (!token) return { error: true };
  const user = await me(token);
  if (!user?.org_id) return { error: true };

  const name = String(form.get("name") ?? "").trim();
  const type = String(form.get("type") ?? "INTERNAL") === "EXTERNAL" ? "EXTERNAL" : "INTERNAL";
  const teamId = String(form.get("team_id") ?? "") || null;
  const personalization = form.get("personalization_enabled") != null;
  const webSearch = form.get("web_search_enabled") != null;
  if (!name) return { error: true };

  const ok = await createWorkspace(token, user.org_id, {
    name,
    type,
    team_id: teamId,
    personalization_enabled: personalization,
    web_search_enabled: webSearch,
  });
  revalidatePath("/admin/workspaces");
  if (teamId) revalidatePath(`/admin/teams/${teamId}`);
  return ok ? { ok: true } : { error: true };
}

// Toggle a per-workspace chat-intelligence flag (personalization / web search / memory).
export async function setWorkspaceFlagAction(
  workspaceId: string,
  field: WorkspaceFlag,
  enabled: boolean,
): Promise<boolean> {
  // Callable directly: never forward an arbitrary field name.
  if (!isWorkspaceFlag(field)) return false;
  const token = await getFreshAccessToken();
  if (!token) return false;
  const ok = await updateWorkspaceSettings(token, workspaceId, workspaceFlagBody(field, enabled));
  if (ok) revalidatePath("/admin/workspaces");
  return ok;
}

export type WidgetOriginsResult =
  | { ok: true; origins: string[] }
  | { ok: false; error: "invalid" | "forbidden" | "failed" };

// Replace a workspace's widget allowed origins. Re-validates server-side (the
// action is callable directly, not only through the editor).
export async function setWidgetOriginsAction(
  workspaceId: string,
  origins: string[],
): Promise<WidgetOriginsResult> {
  const token = await getFreshAccessToken();
  if (!token) return { ok: false, error: "forbidden" };
  const cleaned: string[] = [];
  for (const raw of origins) {
    const r = normalizeOrigin(raw);
    if (!r.ok) return { ok: false, error: "invalid" };
    if (!cleaned.includes(r.origin)) cleaned.push(r.origin);
  }
  const res = await updateWidgetOrigins(token, workspaceId, cleaned);
  if (!res.ok) {
    if (res.status === 422) return { ok: false, error: "invalid" };
    if (res.status === 401 || res.status === 403 || res.status === 404) return { ok: false, error: "forbidden" };
    return { ok: false, error: "failed" };
  }
  revalidatePath("/admin/workspaces");
  return { ok: true, origins: res.origins };
}
