// SPDX-License-Identifier: Apache-2.0

"use server";

import { revalidatePath } from "next/cache";

import { changeMyPassword, clearMyMemory, importMemory, updateMyProfile, updatePreferences, type AnswerStyle } from "@/lib/api";
import { memoryImportError, type MemoryImportError } from "@/lib/memory-import";
import { isPasswordPolicyRejection, passwordPolicyError } from "@/lib/password-policy";
import { getFreshAccessToken } from "@/lib/session";

export type ProfileFormState = { ok?: boolean; error?: boolean };
export type PasswordFormState = {
  ok?: boolean;
  error?: "current" | "mismatch" | "short" | "policy" | "generic";
};

export async function updateProfileAction(
  _prev: ProfileFormState,
  formData: FormData,
): Promise<ProfileFormState> {
  const token = await getFreshAccessToken();
  if (!token) return { error: true };
  const str = (k: string) => String(formData.get(k) ?? "").trim();
  const res = await updateMyProfile(token, {
    full_name: str("full_name") || null,
    job_title: str("job_title") || null,
    department: str("department") || null,
    phone: str("phone") || null,
    location: str("location") || null,
    timezone: str("timezone") || null,
  });
  if (!res.ok) return { error: true };
  revalidatePath("/account");
  return { ok: true };
}

export type PreferencesFormState = { ok?: boolean; error?: boolean };

export async function updatePreferencesAction(
  _prev: PreferencesFormState,
  formData: FormData,
): Promise<PreferencesFormState> {
  const token = await getFreshAccessToken();
  if (!token) return { error: true };
  const style = String(formData.get("answer_style") ?? "").trim();
  const model = String(formData.get("preferred_chat_model") ?? "").trim();
  const allowed: AnswerStyle[] = ["corporate", "short", "instructive", "balanced"];
  const res = await updatePreferences(token, {
    answer_style: allowed.includes(style as AnswerStyle) ? (style as AnswerStyle) : undefined,
    preferred_chat_model: model === "" ? null : model,
  });
  if (!res.ok) return { error: true };
  revalidatePath("/account");
  return { ok: true };
}

export async function changePasswordAction(
  _prev: PasswordFormState,
  formData: FormData,
): Promise<PasswordFormState> {
  const token = await getFreshAccessToken();
  if (!token) return { error: "generic" };
  const current = String(formData.get("current_password") ?? "");
  const next = String(formData.get("new_password") ?? "");
  const confirm = String(formData.get("confirm_password") ?? "");
  const policy = passwordPolicyError(next);
  if (policy) return { error: policy === "long" ? "policy" : "short" };
  if (next !== confirm) return { error: "mismatch" };
  const res = await changeMyPassword(token, {
    current_password: current,
    new_password: next,
  });
  if (res.ok) return { ok: true };
  if (isPasswordPolicyRejection(res.status, res.data)) return { error: "policy" };
  if (res.status === 400) return { error: "current" };
  return { error: "generic" };
}

export async function clearMemoryAction(): Promise<boolean> {
  const token = await getFreshAccessToken();
  if (!token) return false;
  const res = await clearMyMemory(token);
  if (res.ok) revalidatePath("/account");
  return res.ok;
}

// Import a memory summary pasted from another assistant. The backend parses the
// free text into discrete facts and returns how many it added.
export type MemoryImportState = {
  ok?: boolean;
  added?: number;
  error?: MemoryImportError;
};

export async function importMemoryAction(
  _prev: MemoryImportState,
  formData: FormData,
): Promise<MemoryImportState> {
  const token = await getFreshAccessToken();
  if (!token) return { error: "generic" };
  const text = String(formData.get("memory_text") ?? "").trim();
  if (!text) return { error: "empty" };
  const res = await importMemory(token, text);
  if (res.ok) {
    const added = Number((res.data as { added?: number } | undefined)?.added ?? 0);
    revalidatePath("/account");
    return { ok: true, added };
  }
  return { error: memoryImportError(res.status) };
}
