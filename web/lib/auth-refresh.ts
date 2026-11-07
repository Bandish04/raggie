// SPDX-License-Identifier: Apache-2.0

// Single-flight access-token refresh.
//
// The control plane rotates the refresh token on every /auth/refresh and, if a
// rotated-out token is ever presented again, revokes the whole session. Several
// requests (parallel fetches, several tabs sharing the cookie) can find the
// access token expired at the same moment, so refreshes are deduplicated per
// refresh token: concurrent callers share one in-flight call, and for a short
// grace window afterwards a request still carrying the old cookie (it left the
// browser before the rotated cookie landed) receives the same new tokens
// instead of replaying the old one upstream.
//
// The dedupe state is per process (shared between proxy.ts and route handlers
// via globalThis, since Next bundles them separately). With several web
// replicas, route a session to one replica (sticky sessions) or accept that a
// cross-replica race can end that session.
//
// Pure apart from the default control-plane call: unit-testable with node:test.

export type Tokens = { access_token: string; refresh_token: string };

/** "invalid": the control plane rejected the refresh token (expired, revoked,
 *  reused) — the session is over. "unavailable": transient (network, 5xx,
 *  429) — keep the cookies and try again later. */
export type RefreshOutcome =
  | { ok: true; tokens: Tokens }
  | { ok: false; reason: "invalid" | "unavailable" };

export type RefreshFn = (refreshToken: string, headers?: Record<string, string>) => Promise<RefreshOutcome>;

type Entry = { promise: Promise<RefreshOutcome>; settledAt?: number; outcome?: RefreshOutcome };

const DEFAULT_GRACE_MS = 60_000;
// An "invalid" result is shared briefly so a burst of requests does not hammer
// the control plane with a token it already rejected.
const INVALID_TTL_MS = 5_000;
const MAX_ENTRIES = 10_000;

export function createRefresher(
  doRefresh: RefreshFn,
  opts: { graceMs?: number; now?: () => number } = {},
): RefreshFn {
  const graceMs = opts.graceMs ?? DEFAULT_GRACE_MS;
  const now = opts.now ?? Date.now;
  const entries = new Map<string, Entry>();

  const ttl = (o: RefreshOutcome) => (o.ok ? graceMs : o.reason === "invalid" ? INVALID_TTL_MS : 0);

  function prune(t: number) {
    for (const [key, e] of entries) {
      if (e.outcome && e.settledAt !== undefined && t - e.settledAt > ttl(e.outcome)) entries.delete(key);
    }
    // Hard cap: drop the oldest settled entries first (Map keeps insertion order).
    for (const [key, e] of entries) {
      if (entries.size <= MAX_ENTRIES) break;
      if (e.outcome) entries.delete(key);
    }
  }

  return (refreshToken, headers) => {
    const t = now();
    prune(t);
    const existing = entries.get(refreshToken);
    if (existing) return existing.promise;

    const entry: Entry = {
      promise: doRefresh(refreshToken, headers)
        .catch((): RefreshOutcome => ({ ok: false, reason: "unavailable" }))
        .then((outcome) => {
          entry.outcome = outcome;
          entry.settledAt = now();
          if (ttl(outcome) === 0) entries.delete(refreshToken);
          return outcome;
        }),
    };
    entries.set(refreshToken, entry);
    return entry.promise;
  };
}

/** True when the JWT's `exp` is within `skewSeconds` of now (or past). Tokens
 *  that cannot be decoded return false: the upstream stays the authority. */
export function tokenExpiresWithin(jwt: string, skewSeconds: number, nowMs = Date.now()): boolean {
  const payload = jwt.split(".")[1];
  if (!payload) return false;
  try {
    const b64 = payload.replace(/-/g, "+").replace(/_/g, "/");
    const claims = JSON.parse(atob(b64.padEnd(b64.length + ((4 - (b64.length % 4)) % 4), "="))) as {
      exp?: unknown;
    };
    if (typeof claims.exp !== "number") return false;
    return claims.exp * 1000 - nowMs <= skewSeconds * 1000;
  } catch {
    return false;
  }
}

async function callControlPlaneRefresh(
  refreshToken: string,
  headers: Record<string, string> = {},
): Promise<RefreshOutcome> {
  const base = process.env.CONTROL_PLANE_URL ?? "http://localhost:8000";
  const res = await fetch(`${base}/api/v1/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: JSON.stringify({ refresh_token: refreshToken }),
    cache: "no-store",
  });
  if (res.ok) {
    const data = (await res.json()) as Partial<Tokens>;
    if (data.access_token && data.refresh_token) {
      return { ok: true, tokens: { access_token: data.access_token, refresh_token: data.refresh_token } };
    }
    return { ok: false, reason: "unavailable" };
  }
  return { ok: false, reason: res.status === 401 || res.status === 403 ? "invalid" : "unavailable" };
}

const GLOBAL_KEY = Symbol.for("raggie.web.refreshSession");

/** Process-wide single-flight refresh against the control plane. `headers` are
 *  extra request headers (X-Forwarded-For/-Proto) for the upstream call. */
export const refreshSession: RefreshFn = (refreshToken, headers) => {
  const g = globalThis as typeof globalThis & { [GLOBAL_KEY]?: RefreshFn };
  g[GLOBAL_KEY] ??= createRefresher(callControlPlaneRefresh);
  return g[GLOBAL_KEY](refreshToken, headers);
};
