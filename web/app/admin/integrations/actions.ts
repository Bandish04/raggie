// SPDX-License-Identifier: Apache-2.0

"use server";

import { revalidatePath } from "next/cache";

import { connectIntegration, deleteIntegration } from "@/lib/api";
import { getFreshAccessToken } from "@/lib/session";

export async function connectIntegrationAction(input: {
  provider: string;
  // Omitted for org-scoped providers (the server forces org scope). Required
  // for workspace-scoped providers.
  workspaceId?: string;
  displayName?: string;
  credentials: Record<string, string>;
  config: Record<string, string>;
}): Promise<{ ok: boolean; error?: string }> {
  const token = await getFreshAccessToken();
  if (!token) return { ok: false };
  // No workspace → organization-wide connect: send only provider + creds/config
  // and let the backend force org scope (SUPER_ADMIN only).
  const body = input.workspaceId
    ? {
        provider: input.provider,
        scope_type: "workspace" as const,
        scope_id: input.workspaceId,
        target_workspace_id: input.workspaceId,
        display_name: input.displayName,
        credentials: input.credentials,
        config: input.config,
      }
    : {
        provider: input.provider,
        display_name: input.displayName,
        credentials: input.credentials,
        config: input.config,
      };
  const res = await connectIntegration(token, body);
  if (res.ok) {
    revalidatePath("/admin/marketplace");
    revalidatePath("/admin/integrations");
  }
  const data = res.data as { detail?: string } | undefined;
  return { ok: res.ok, error: res.ok ? undefined : data?.detail };
}

export async function disconnectIntegrationAction(id: string): Promise<boolean> {
  const token = await getFreshAccessToken();
  if (!token) return false;
  const res = await deleteIntegration(token, id);
  if (res.ok) {
    revalidatePath("/admin/marketplace");
    revalidatePath("/admin/integrations");
  }
  return res.ok;
}
