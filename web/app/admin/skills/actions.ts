// SPDX-License-Identifier: Apache-2.0

"use server";

import { revalidatePath } from "next/cache";

import { type SkillInput, createSkill, deleteSkill, me, updateSkill } from "@/lib/api";
import { getFreshAccessToken } from "@/lib/session";

// Result shape mirrors the directory actions: a `duplicate` flag so the client
// can surface the HTTP 409 (slug already taken) with a friendly message.
export type SkillActionState = {
  ok?: boolean;
  error?: boolean;
  duplicate?: boolean;
};

// Re-check the caller is WORKSPACE_ADMIN+ (the control plane re-enforces). Keep
// STAFF out — they never reach the builder, but actions must guard regardless.
async function token(): Promise<string | null> {
  const t = await getFreshAccessToken();
  if (!t) return null;
  const user = await me(t);
  if (!user || user.role === "STAFF") return null;
  return t;
}

function fail(status: number): SkillActionState {
  return status === 409 ? { duplicate: true } : { error: true };
}

export async function createSkillAction(input: SkillInput): Promise<SkillActionState> {
  const t = await token();
  if (!t) return { error: true };
  const res = await createSkill(t, input);
  if (!res.ok) return fail(res.status);
  revalidatePath("/admin/skills");
  return { ok: true };
}

export async function updateSkillAction(
  id: string,
  input: SkillInput,
): Promise<SkillActionState> {
  const t = await token();
  if (!t) return { error: true };
  const res = await updateSkill(t, id, input);
  if (!res.ok) return fail(res.status);
  revalidatePath("/admin/skills");
  return { ok: true };
}

export async function deleteSkillAction(id: string): Promise<boolean> {
  const t = await token();
  if (!t) return false;
  const res = await deleteSkill(t, id);
  if (res.ok) revalidatePath("/admin/skills");
  return res.ok;
}
