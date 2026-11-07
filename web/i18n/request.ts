// SPDX-License-Identifier: Apache-2.0

import { cookies } from "next/headers";
import { getRequestConfig } from "next-intl/server";

export const SUPPORTED_LOCALES = ["tr", "en"] as const;
export type Locale = (typeof SUPPORTED_LOCALES)[number];

export const LOCALE_COOKIE = "NEXT_LOCALE";

// No-routing i18n: the active locale comes from a cookie, falling back to
// NEXT_PUBLIC_DEFAULT_LOCALE (default en), so URLs stay clean (no /tr, /en prefix).
export default getRequestConfig(async () => {
  const store = await cookies();
  const fromCookie = store.get(LOCALE_COOKIE)?.value;
  const configured = process.env.NEXT_PUBLIC_DEFAULT_LOCALE ?? "";
  const fallback: Locale = (SUPPORTED_LOCALES as readonly string[]).includes(configured)
    ? (configured as Locale)
    : "en";
  const locale = (SUPPORTED_LOCALES as readonly string[]).includes(fromCookie ?? "")
    ? (fromCookie as Locale)
    : fallback;

  return {
    locale,
    messages: (await import(`../messages/${locale}.json`)).default,
  };
});
