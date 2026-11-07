// SPDX-License-Identifier: Apache-2.0

"use server";

import { redirect } from "next/navigation";

import { login, me } from "@/lib/api";
import type { LoginError } from "@/lib/login-error";
import { setSession } from "@/lib/session";

export type LoginState = { error?: LoginError["error"]; retryAfterMinutes?: number };

export async function loginAction(_prev: LoginState, formData: FormData): Promise<LoginState> {
  const email = String(formData.get("email") ?? "");
  const password = String(formData.get("password") ?? "");

  const result = await login(email, password);
  if (!result.ok) {
    const f = result.failure;
    return f.error === "locked" ? { error: "locked", retryAfterMinutes: f.retryAfterMinutes } : { error: f.error };
  }
  const tokens = result.tokens;
  await setSession(tokens);
  // Plain members (STAFF) have no admin surfaces — land them straight in chat.
  // Admins keep the dashboard as their home.
  const user = await me(tokens.access_token);
  redirect(user?.role === "STAFF" ? "/chat" : "/dashboard");
}
