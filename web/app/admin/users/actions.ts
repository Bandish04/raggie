// SPDX-License-Identifier: Apache-2.0

"use server";

import { revalidatePath } from "next/cache";

import {
  createOrgUser,
  me,
  resetOrgUserPassword,
  setOrgUserActive,
  setPlatformAdmin,
  updateOrgUser,
} from "@/lib/api";
import { isPasswordPolicyRejection, passwordPolicyError } from "@/lib/password-policy";
import { platformAdminError, type PlatformAdminError } from "@/lib/permissions";
import { getFreshAccessToken } from "@/lib/session";

export type UserFormState = {
  ok?: boolean;
  error?: boolean;
  passwordError?: boolean; // the chosen password violates the password policy
  tempPassword?: string; // shown once after a create with a generated password
};

async function ctx(): Promise<{ token: string; orgId: string } | null> {
  const token = await getFreshAccessToken();
  if (!token) return null;
  const profile = await me(token);
  if (!profile?.org_id) return null;
  return { token, orgId: profile.org_id };
}

function profileFromForm(formData: FormData) {
  const str = (k: string) => String(formData.get(k) ?? "").trim();
  const val = (k: string) => str(k) || undefined;
  return {
    full_name: val("full_name"),
    job_title: val("job_title"),
    // Managed directory references; the backend fills the legacy `department`
    // TEXT from department_id (write-through), so we no longer send free text.
    department_id: val("department_id"),
    location_id: val("location_id"),
    manager_user_id: val("manager_user_id"),
    phone: val("phone"),
    location: val("location"),
    timezone: val("timezone"),
    locale: val("locale"),
    hire_date: val("hire_date"),
  };
}

export async function createUserAction(
  _prev: UserFormState,
  formData: FormData,
): Promise<UserFormState> {
  const c = await ctx();
  if (!c) return { error: true };
  const email = String(formData.get("email") ?? "").trim();
  const role = String(formData.get("role") ?? "STAFF");
  if (!email) return { error: true };
  // Optional: blank → the control plane generates a temp password.
  const password = String(formData.get("password") ?? "");
  if (password && passwordPolicyError(password)) return { passwordError: true };
  const res = await createOrgUser(c.token, c.orgId, {
    email,
    role,
    ...(password ? { password } : {}),
    ...profileFromForm(formData),
  });
  if (isPasswordPolicyRejection(res.status, res.data)) return { passwordError: true };
  if (!res.ok) return { error: true };
  revalidatePath("/admin/users");
  const data = res.data as { temp_password?: string } | undefined;
  return { ok: true, tempPassword: data?.temp_password };
}

export async function updateUserAction(
  _prev: UserFormState,
  formData: FormData,
): Promise<UserFormState> {
  const c = await ctx();
  if (!c) return { error: true };
  const userId = String(formData.get("user_id") ?? "");
  if (!userId) return { error: true };
  const role = String(formData.get("role") ?? "");
  const p = profileFromForm(formData);
  // Empty strings clear a field; send null so the backend nulls it out.
  const res = await updateOrgUser(c.token, c.orgId, userId, {
    role: role || undefined,
    full_name: p.full_name ?? null,
    job_title: p.job_title ?? null,
    department_id: p.department_id ?? null,
    location_id: p.location_id ?? null,
    manager_user_id: p.manager_user_id ?? null,
    phone: p.phone ?? null,
    location: p.location ?? null,
    timezone: p.timezone ?? undefined,
    locale: p.locale ?? undefined,
    hire_date: p.hire_date ?? null,
  });
  if (!res.ok) return { error: true };
  revalidatePath("/admin/users");
  return { ok: true };
}

export async function setUserActive(userId: string, active: boolean): Promise<boolean> {
  const c = await ctx();
  if (!c) return false;
  const res = await setOrgUserActive(c.token, c.orgId, userId, active);
  if (res.ok) revalidatePath("/admin/users");
  return res.ok;
}

export async function resetPassword(
  userId: string,
): Promise<{ ok: boolean; tempPassword?: string }> {
  const c = await ctx();
  if (!c) return { ok: false };
  const res = await resetOrgUserPassword(c.token, c.orgId, userId);
  const data = res.data as { temp_password?: string } | undefined;
  return { ok: res.ok, tempPassword: data?.temp_password };
}

export async function setPlatformAdminAction(
  userId: string,
  value: boolean,
): Promise<{ ok: boolean; error?: PlatformAdminError }> {
  const token = await getFreshAccessToken();
  if (!token) return { ok: false, error: "generic" };
  const res = await setPlatformAdmin(token, userId, value);
  if (res.ok) {
    revalidatePath("/admin/organization");
    return { ok: true };
  }
  const detail = (res.data as { detail?: unknown } | undefined)?.detail;
  return { ok: false, error: platformAdminError(res.status, typeof detail === "string" ? detail : undefined) };
}
