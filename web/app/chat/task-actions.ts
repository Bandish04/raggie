// SPDX-License-Identifier: Apache-2.0

"use server";

import { revalidatePath } from "next/cache";

import {
  type AnswerStyle,
  type ScheduledTaskInput,
  type ScheduledTaskPatch,
  createScheduledTask,
  deleteNotification,
  deleteScheduledTask,
  markAllNotificationsRead,
  markNotificationRead,
  updateScheduledTask,
} from "@/lib/api";
import { getFreshAccessToken } from "@/lib/session";

// Scheduled-task + notification server actions. Mirror the chat skill-actions
// state shape: a small { ok, error } object the client surfaces as a calm error.
// The control plane re-enforces ownership (current-user scoped); these just relay
// + revalidate the chat route so the modal/inbox refetch after a mutation.
export type TaskActionState = {
  ok?: boolean;
  // Generic failure (network/server) or a 400 (bad cron / bad workspace) — both
  // surface the same friendly "couldn't save" message in the form.
  error?: boolean;
};

// Coerce the optional answer-style select ("" = no override) back to the union.
function asStyle(v: unknown): AnswerStyle | null {
  return v === "corporate" || v === "short" || v === "instructive" || v === "balanced"
    ? v
    : null;
}

export async function createScheduledTaskAction(
  input: ScheduledTaskInput,
): Promise<TaskActionState> {
  const t = await getFreshAccessToken();
  if (!t) return { error: true };
  const res = await createScheduledTask(t, {
    ...input,
    answer_style: asStyle(input.answer_style),
  });
  if (!res.ok) return { error: true };
  revalidatePath("/chat");
  return { ok: true };
}

// Also used for the enable/disable toggle (a single-field { enabled } patch).
export async function updateScheduledTaskAction(
  id: string,
  patch: ScheduledTaskPatch,
): Promise<TaskActionState> {
  const t = await getFreshAccessToken();
  if (!t) return { error: true };
  const res = await updateScheduledTask(t, id, {
    ...patch,
    ...("answer_style" in patch ? { answer_style: asStyle(patch.answer_style) } : {}),
  });
  if (!res.ok) return { error: true };
  revalidatePath("/chat");
  return { ok: true };
}

export async function deleteScheduledTaskAction(id: string): Promise<TaskActionState> {
  const t = await getFreshAccessToken();
  if (!t) return { error: true };
  const res = await deleteScheduledTask(t, id);
  if (!res.ok) return { error: true };
  revalidatePath("/chat");
  return { ok: true };
}

export async function markNotifReadAction(id: string): Promise<TaskActionState> {
  const t = await getFreshAccessToken();
  if (!t) return { error: true };
  const res = await markNotificationRead(t, id);
  if (!res.ok) return { error: true };
  revalidatePath("/chat");
  return { ok: true };
}

export async function markAllNotifReadAction(): Promise<TaskActionState> {
  const t = await getFreshAccessToken();
  if (!t) return { error: true };
  const res = await markAllNotificationsRead(t);
  if (!res.ok) return { error: true };
  revalidatePath("/chat");
  return { ok: true };
}

export async function deleteNotifAction(id: string): Promise<TaskActionState> {
  const t = await getFreshAccessToken();
  if (!t) return { error: true };
  const res = await deleteNotification(t, id);
  if (!res.ok) return { error: true };
  revalidatePath("/chat");
  return { ok: true };
}
