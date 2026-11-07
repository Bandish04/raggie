// SPDX-License-Identifier: Apache-2.0

"use server";

import { revalidatePath } from "next/cache";
import { cookies } from "next/headers";

import { setMyLocale } from "@/lib/api";
import { getFreshAccessToken } from "@/lib/session";

export async function setLocale(locale: "tr" | "en"): Promise<void> {
  (await cookies()).set("NEXT_LOCALE", locale, {
    path: "/",
    sameSite: "lax",
    maxAge: 60 * 60 * 24 * 365, // persist a year, not just the session
  });
  // For an authenticated user, also persist the choice to their account so it
  // follows them across devices/sessions (anonymous visitors stay cookie-only).
  const token = await getFreshAccessToken();
  if (token) {
    try {
      await setMyLocale(token, locale);
    } catch {
      /* best-effort — the cookie already took effect */
    }
  }
  // i18n/request.ts reads the cookie per request; revalidate the layout so a
  // client router.refresh() re-renders the RSC tree in the new locale (no reload).
  revalidatePath("/", "layout");
}
