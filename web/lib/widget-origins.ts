// SPDX-License-Identifier: Apache-2.0

// Client-side validation for a workspace's widget allowed origins.
//
// Mirrors the control-plane rule (services/control-plane/.../api/workspaces.py:
// scheme://host[:port], http(s) only, no path, no wildcard) and additionally
// normalizes to the exact string a browser sends in its Origin header
// (lowercase, no default port, punycode host). The edge compares that header
// byte-for-byte against the stored list, so "https://Shop.example.com:443/"
// would otherwise be accepted by the API yet never match.

export type OriginError = "empty" | "wildcard" | "scheme" | "path" | "invalid" | "duplicate";

export type OriginResult = { ok: true; origin: string } | { ok: false; reason: Exclude<OriginError, "duplicate"> };

// Same shape the control plane accepts; checked after URL normalization.
const ORIGIN_RE = /^https?:\/\/[a-zA-Z0-9.-]+(:\d{1,5})?$/;
const SCHEME_RE = /^([a-zA-Z][a-zA-Z0-9+.-]*):/;

export function normalizeOrigin(raw: string): OriginResult {
  const input = raw.trim();
  if (!input) return { ok: false, reason: "empty" };
  if (input.includes("*")) return { ok: false, reason: "wildcard" };

  const scheme = input.match(SCHEME_RE)?.[1]?.toLowerCase();
  if (scheme !== "http" && scheme !== "https") return { ok: false, reason: "scheme" };

  let url: URL;
  try {
    url = new URL(input);
  } catch {
    return { ok: false, reason: "invalid" };
  }
  if (url.username || url.password) return { ok: false, reason: "invalid" };
  if (url.pathname !== "/" || url.search || url.hash || /[?#]/.test(input)) {
    return { ok: false, reason: "path" };
  }
  if (!ORIGIN_RE.test(url.origin)) return { ok: false, reason: "invalid" };
  return { ok: true, origin: url.origin };
}

export function addOrigin(
  origins: readonly string[],
  raw: string,
): { ok: true; origins: string[] } | { ok: false; reason: OriginError } {
  const result = normalizeOrigin(raw);
  if (!result.ok) return result;
  if (origins.includes(result.origin)) return { ok: false, reason: "duplicate" };
  return { ok: true, origins: [...origins, result.origin] };
}

export function removeOrigin(origins: readonly string[], origin: string): string[] {
  return origins.filter((o) => o !== origin);
}
