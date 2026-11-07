// SPDX-License-Identifier: Apache-2.0

"use server";

import { revalidatePath } from "next/cache";

import { me, startReembed, updateAiConfig } from "@/lib/api";
import { isFingerprint, reembedErrorKind, type ReembedErrorKind, type ReembedResult } from "@/lib/embeddings";
import { isPlatformAdmin } from "@/lib/permissions";
import { getFreshAccessToken } from "@/lib/session";

export type AiConfigActionState = { ok?: boolean; error?: boolean };

/**
 * Persist the chat AI config (default model + allowed models). Platform admin only;
 * the control plane re-enforces. The LLM endpoint/key live in the edge env by
 * design — only model SELECTION is managed here.
 */
export async function saveAiConfigAction(input: {
  default_model: string | null;
  allowed_models: string[];
  // Display aliases: real model id -> friendly name shown to users.
  aliases: Record<string, string>;
}): Promise<AiConfigActionState> {
  const token = await getFreshAccessToken();
  if (!token) return { error: true };
  const user = await me(token);
  if (!isPlatformAdmin(user)) return { error: true };

  const res = await updateAiConfig(token, {
    chat_default_model: input.default_model,
    chat_allowed_models: input.allowed_models,
    chat_model_aliases: input.aliases,
  });
  if (!res.ok) return { error: true };
  revalidatePath("/admin/ai");
  return { ok: true };
}

export type ReembedActionResult =
  | { ok: true; result: ReembedResult }
  | { ok: false; error: ReembedErrorKind };

/**
 * Accept the embeddings gateway's current profile and re-embed every live
 * document still on another one. Platform admin only; the control plane
 * re-enforces and refuses (409) when the gateway changed since the admin looked.
 */
export async function reembedAction(fingerprint: string): Promise<ReembedActionResult> {
  if (!isFingerprint(fingerprint)) return { ok: false, error: "invalid" };
  const token = await getFreshAccessToken();
  if (!token) return { ok: false, error: "forbidden" };
  const user = await me(token);
  if (!isPlatformAdmin(user)) return { ok: false, error: "forbidden" };

  const res = await startReembed(token, fingerprint);
  if (!res.ok) return { ok: false, error: reembedErrorKind(res.status) };
  const d = res.data as Partial<ReembedResult> | undefined;
  revalidatePath("/admin/ai");
  return {
    ok: true,
    result: {
      fingerprint: d?.fingerprint ?? fingerprint,
      collection: d?.collection ?? "",
      reembedded: d?.reembedded ?? 0,
      skipped: d?.skipped ?? 0,
      workspaces: d?.workspaces ?? 0,
    },
  };
}
