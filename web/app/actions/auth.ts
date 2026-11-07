// SPDX-License-Identifier: Apache-2.0

"use server";

import { redirect } from "next/navigation";

import { logout } from "@/lib/api";
import { clearSession, getFreshAccessToken } from "@/lib/session";

export async function signOutAction(): Promise<void> {
  const token = await getFreshAccessToken();
  if (token) {
    try {
      await logout(token);
    } catch {
      // Local cookie cleanup must still succeed if the control plane is down.
    }
  }
  await clearSession();
  redirect("/login");
}
