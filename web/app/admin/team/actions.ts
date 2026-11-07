// SPDX-License-Identifier: Apache-2.0

"use server";

import { revalidatePath } from "next/cache";

import { createInvite, resendInvite, revokeInvite } from "@/lib/api";
import { getFreshAccessToken } from "@/lib/session";

export type InviteState = { ok?: boolean; error?: boolean; acceptPath?: string };

export async function createInviteAction(
  _prev: InviteState,
  formData: FormData,
): Promise<InviteState> {
  const token = await getFreshAccessToken();
  if (!token) return { error: true };
  const str = (k: string) => String(formData.get(k) ?? "").trim();
  const val = (k: string) => str(k) || undefined;
  const email = str("email");
  const role = str("role") || "STAFF";
  if (!email) return { error: true };
  const res = await createInvite(token, email, role as "WORKSPACE_ADMIN" | "STAFF", {
    workspaceId: val("workspace_id"),
    teamId: val("team_id"),
    full_name: val("full_name"),
    job_title: val("job_title"),
    // Department/location are seeded as TEXT (the value the chat persona reads),
    // chosen from the managed directory in the form. The invite carries TEXT only.
    department: val("department"),
    location: val("location"),
    manager_user_id: val("manager_user_id"),
    phone: val("phone"),
    timezone: val("timezone"),
    locale: val("locale"),
  });
  if (!res) return { error: true };
  revalidatePath("/admin/team");
  return { ok: true, acceptPath: res.accept_path };
}

export async function revokeInviteAction(inviteId: string): Promise<boolean> {
  const token = await getFreshAccessToken();
  if (!token) return false;
  const res = await revokeInvite(token, inviteId);
  if (res.ok) revalidatePath("/admin/team");
  return res.ok;
}

export async function resendInviteAction(
  inviteId: string,
): Promise<{ ok: boolean; acceptPath?: string }> {
  const token = await getFreshAccessToken();
  if (!token) return { ok: false };
  const res = await resendInvite(token, inviteId);
  if (!res.ok) return { ok: false };
  revalidatePath("/admin/team");
  const data = res.data as { accept_path?: string } | undefined;
  return { ok: true, acceptPath: data?.accept_path };
}
