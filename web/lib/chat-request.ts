// SPDX-License-Identifier: Apache-2.0

// /api/chat request shaping. The chat UI sends `locale` itself; this fills it in
// for any other caller so the edge always gets the UI language (it selects the
// prompt template and server-authored text). Malformed bodies pass through
// untouched — the edge answers them with its own 400.
export function withDefaultLocale(body: string, locale: string): string {
  let parsed: unknown;
  try {
    parsed = JSON.parse(body);
  } catch {
    return body;
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return body;
  const obj = parsed as Record<string, unknown>;
  if (typeof obj.locale === "string" && obj.locale) return body;
  return JSON.stringify({ ...obj, locale });
}
