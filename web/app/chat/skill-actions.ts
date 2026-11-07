// SPDX-License-Identifier: Apache-2.0

"use server";

import { revalidatePath } from "next/cache";

import { type SkillInput, createMySkill, deleteMySkill, updateMySkill } from "@/lib/api";
import { getFreshAccessToken } from "@/lib/session";

// Personal-skill server actions. Mirror the admin skill actions' state shape and
// FormData field names so the chat modal stays familiar — but these are NOT admin
// gated: any logged-in user manages their OWN skills (the backend re-enforces
// ownership). 409 surfaces as `duplicate` (the personal slug is already taken).
export type SkillActionState = {
  ok?: boolean;
  error?: boolean;
  duplicate?: boolean;
};

function fail(status: number): SkillActionState {
  return status === 409 ? { duplicate: true } : { error: true };
}

// Translate the shared FormData (same field names as the admin modal) into the
// SkillInput body. The optional model / answer_style selects emit "" for "no
// override", which maps back to null.
function parseBody(formData: FormData): SkillInput {
  const str = (k: string) => (formData.get(k)?.toString() ?? "").trim();
  const model = str("model");
  const answerStyle = str("answer_style");
  return {
    name: str("name"),
    slug: str("slug"),
    description: str("description") || null,
    instructions: str("instructions"),
    icon: str("icon") || null,
    model: model || null,
    answer_style:
      answerStyle === "corporate" ||
      answerStyle === "short" ||
      answerStyle === "instructive" ||
      answerStyle === "balanced"
        ? answerStyle
        : null,
    allowed_tools: formData.getAll("allowed_tools").map((value) => value.toString()),
    enabled: true,
  };
}

export async function createMySkillAction(
  _prev: SkillActionState,
  formData: FormData,
): Promise<SkillActionState> {
  const t = await getFreshAccessToken();
  if (!t) return { error: true };
  const res = await createMySkill(t, parseBody(formData));
  if (!res.ok) return fail(res.status);
  revalidatePath("/chat");
  return { ok: true };
}

export async function updateMySkillAction(
  _prev: SkillActionState,
  formData: FormData,
): Promise<SkillActionState> {
  const t = await getFreshAccessToken();
  if (!t) return { error: true };
  const id = formData.get("id")?.toString();
  if (!id) return { error: true };
  const res = await updateMySkill(t, id, parseBody(formData));
  if (!res.ok) return fail(res.status);
  revalidatePath("/chat");
  return { ok: true };
}

export async function deleteMySkillAction(id: string): Promise<boolean> {
  const t = await getFreshAccessToken();
  if (!t) return false;
  const res = await deleteMySkill(t, id);
  if (res.ok) revalidatePath("/chat");
  return res.ok;
}
