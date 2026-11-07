// SPDX-License-Identifier: Apache-2.0

"use server";

import { revalidatePath } from "next/cache";

import { addTeamMember, createTeam, me, removeTeamMember, type Role } from "@/lib/api";
import { getFreshAccessToken } from "@/lib/session";

export type TeamActionState = { ok?: boolean; error?: boolean };

async function orgCtx(): Promise<{ token: string; orgId: string } | null> {
  const token = await getFreshAccessToken();
  if (!token) return null;
  const user = await me(token);
  if (!user?.org_id) return null;
  return { token, orgId: user.org_id };
}

export async function createTeamAction(
  _prev: TeamActionState,
  form: FormData,
): Promise<TeamActionState> {
  const ctx = await orgCtx();
  if (!ctx) return { error: true };
  const name = String(form.get("name") ?? "").trim();
  if (!name) return { error: true };
  const parent = String(form.get("parent_team_id") ?? "") || undefined;
  const ok = await createTeam(ctx.token, ctx.orgId, name, parent);
  revalidatePath("/admin/teams");
  return ok ? { ok: true } : { error: true };
}

export async function addTeamMemberAction(
  _prev: TeamActionState,
  form: FormData,
): Promise<TeamActionState> {
  const ctx = await orgCtx();
  if (!ctx) return { error: true };
  const teamId = String(form.get("team_id") ?? "");
  const userId = String(form.get("user_id") ?? "");
  const role: Role =
    String(form.get("role") ?? "STAFF") === "WORKSPACE_ADMIN" ? "WORKSPACE_ADMIN" : "STAFF";
  if (!teamId || !userId) return { error: true };
  const ok = await addTeamMember(ctx.token, ctx.orgId, teamId, userId, role);
  revalidatePath(`/admin/teams/${teamId}`);
  return ok ? { ok: true } : { error: true };
}

export async function removeTeamMemberAction(form: FormData): Promise<void> {
  const ctx = await orgCtx();
  if (!ctx) return;
  const teamId = String(form.get("team_id") ?? "");
  const userId = String(form.get("user_id") ?? "");
  if (!teamId || !userId) return;
  await removeTeamMember(ctx.token, ctx.orgId, teamId, userId);
  revalidatePath(`/admin/teams/${teamId}`);
}
