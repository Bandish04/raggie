// SPDX-License-Identifier: Apache-2.0

"use server";

import { revalidatePath } from "next/cache";

import {
  createDepartment,
  createLocation,
  deleteDepartment,
  deleteLocation,
  me,
  updateDepartment,
  updateLocation,
} from "@/lib/api";
import { getFreshAccessToken } from "@/lib/session";

// Mirrors the result shape used by the team/user actions, plus a `duplicate`
// flag so the client can show a friendly message on an HTTP 409.
export type DirectoryActionState = {
  ok?: boolean;
  error?: boolean;
  duplicate?: boolean;
};

async function ctx(): Promise<{ token: string; orgId: string } | null> {
  const token = await getFreshAccessToken();
  if (!token) return null;
  const profile = await me(token);
  if (!profile?.org_id) return null;
  return { token, orgId: profile.org_id };
}

const str = (fd: FormData, k: string) => String(fd.get(k) ?? "").trim();
const opt = (fd: FormData, k: string) => str(fd, k) || undefined;
// For PATCH: an empty string means "clear this optional reference".
const nullable = (fd: FormData, k: string) => (str(fd, k) ? str(fd, k) : null);

function fail(status: number): DirectoryActionState {
  return status === 409 ? { duplicate: true } : { error: true };
}

// ───────────────────────── Departments ─────────────────────────
export async function createDepartmentAction(
  _prev: DirectoryActionState,
  formData: FormData,
): Promise<DirectoryActionState> {
  const c = await ctx();
  if (!c) return { error: true };
  const name = str(formData, "name");
  if (!name) return { error: true };
  const res = await createDepartment(c.token, c.orgId, {
    name,
    owner_user_id: opt(formData, "owner_user_id") ?? null,
    parent_department_id: opt(formData, "parent_department_id") ?? null,
  });
  if (!res.ok) return fail(res.status);
  revalidatePath("/admin/directory");
  return { ok: true };
}

export async function updateDepartmentAction(
  _prev: DirectoryActionState,
  formData: FormData,
): Promise<DirectoryActionState> {
  const c = await ctx();
  if (!c) return { error: true };
  const deptId = str(formData, "dept_id");
  const name = str(formData, "name");
  if (!deptId || !name) return { error: true };
  const res = await updateDepartment(c.token, c.orgId, deptId, {
    name,
    owner_user_id: nullable(formData, "owner_user_id"),
    parent_department_id: nullable(formData, "parent_department_id"),
  });
  if (!res.ok) return fail(res.status);
  revalidatePath("/admin/directory");
  return { ok: true };
}

export async function deleteDepartmentAction(deptId: string): Promise<boolean> {
  const c = await ctx();
  if (!c) return false;
  const res = await deleteDepartment(c.token, c.orgId, deptId);
  if (res.ok) revalidatePath("/admin/directory");
  return res.ok;
}

// ───────────────────────── Locations ─────────────────────────
export async function createLocationAction(
  _prev: DirectoryActionState,
  formData: FormData,
): Promise<DirectoryActionState> {
  const c = await ctx();
  if (!c) return { error: true };
  const name = str(formData, "name");
  if (!name) return { error: true };
  const res = await createLocation(c.token, c.orgId, {
    name,
    city: opt(formData, "city") ?? null,
    country: opt(formData, "country") ?? null,
  });
  if (!res.ok) return fail(res.status);
  revalidatePath("/admin/directory");
  return { ok: true };
}

export async function updateLocationAction(
  _prev: DirectoryActionState,
  formData: FormData,
): Promise<DirectoryActionState> {
  const c = await ctx();
  if (!c) return { error: true };
  const locId = str(formData, "loc_id");
  const name = str(formData, "name");
  if (!locId || !name) return { error: true };
  const res = await updateLocation(c.token, c.orgId, locId, {
    name,
    city: nullable(formData, "city"),
    country: nullable(formData, "country"),
  });
  if (!res.ok) return fail(res.status);
  revalidatePath("/admin/directory");
  return { ok: true };
}

export async function deleteLocationAction(locId: string): Promise<boolean> {
  const c = await ctx();
  if (!c) return false;
  const res = await deleteLocation(c.token, c.orgId, locId);
  if (res.ok) revalidatePath("/admin/directory");
  return res.ok;
}
