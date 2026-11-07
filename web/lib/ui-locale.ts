// SPDX-License-Identifier: Apache-2.0

// The UI locale for server-side code that has the request but not next-intl's
// request config (route handlers proxying to edge). Same rule as
// i18n/request.ts: a supported NEXT_LOCALE cookie, else the configured default.
export function uiLocale(cookieValue: string | undefined): "tr" | "en" {
  if (cookieValue === "tr" || cookieValue === "en") return cookieValue;
  return process.env.NEXT_PUBLIC_DEFAULT_LOCALE === "en" ? "en" : "tr";
}
