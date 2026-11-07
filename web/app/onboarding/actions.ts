// SPDX-License-Identifier: Apache-2.0

"use server";

import {
  bootstrap,
  createOnboardingWorkspace,
  uploadDocumentResult,
  type WorkspaceSetup,
} from "@/lib/api";
import { passwordPolicyError } from "@/lib/password-policy";
import { getFreshAccessToken, setSession } from "@/lib/session";
import { uploadRefusalMessage, type UploadFailureMessage } from "@/lib/upload-errors";

export type BootstrapError = "invalid_token" | "already_setup" | "weak_password" | "failed";

export async function bootstrapAction(
  email: string,
  password: string,
  orgName: string,
  setupToken: string,
): Promise<{ ok: boolean; error?: BootstrapError }> {
  if (passwordPolicyError(password)) return { ok: false, error: "weak_password" };
  const outcome = await bootstrap(email, password, orgName, setupToken.trim());
  if (!outcome.ok) {
    const error: BootstrapError = outcome.passwordRejected
      ? "weak_password"
      : outcome.status === 401 || outcome.status === 403
        ? "invalid_token"
        : outcome.status === 409
          ? "already_setup"
          : "failed";
    return { ok: false, error };
  }
  await setSession(outcome.result);
  return { ok: true };
}

export async function createWorkspaceAction(
  type: "INTERNAL" | "EXTERNAL",
  name: string,
  inviteEmail?: string,
): Promise<{ ok: boolean; setup?: WorkspaceSetup }> {
  const token = await getFreshAccessToken();
  if (!token) return { ok: false };
  const setup = await createOnboardingWorkspace(token, type, name, inviteEmail || undefined);
  return setup ? { ok: true, setup } : { ok: false };
}

export async function uploadAction(
  workspaceId: string,
  formData: FormData,
): Promise<{ ok: boolean; count: number; refusal?: UploadFailureMessage }> {
  const token = await getFreshAccessToken();
  if (!token) return { ok: false, count: 0 };
  const files = formData
    .getAll("files")
    .filter((f): f is File => f instanceof File && f.size > 0);
  let count = 0;
  for (const file of files) {
    const res = await uploadDocumentResult(token, workspaceId, file);
    if (res.ok) {
      count += 1;
      continue;
    }
    // The embedding-profile guard refuses every file the same way: stop and
    // explain it instead of reporting a silent partial count.
    const refusal = uploadRefusalMessage(res.status, res.body, res.retryAfter);
    if (refusal) return { ok: false, count, refusal };
  }
  return { ok: true, count };
}
