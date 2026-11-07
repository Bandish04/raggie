// SPDX-License-Identifier: Apache-2.0

// Session cookie names and options, shared by lib/session.ts (server
// components, route handlers, actions) and proxy.ts — which cannot import the
// "server-only" session module.

export const ACCESS_COOKIE = "raggie_access";
export const REFRESH_COOKIE = "raggie_refresh";

// Keep users signed in for a full workday by default (8h). The browser drops the
// cookie after maxAge, so this should be >= the access-token TTL on the control
// plane (JWT_ACCESS_TTL_SECONDS). Override with SESSION_TTL_SECONDS if needed.
export const ACCESS_MAX_AGE = Number(process.env.SESSION_TTL_SECONDS ?? 28800); // 8 hours
export const REFRESH_MAX_AGE = 60 * 60 * 24 * 30; // 30 days

// Refresh the access token this many seconds before it expires, so a request
// that starts just before expiry does not fail upstream mid-flight.
export const REFRESH_SKEW_SECONDS = 60;

export function sessionCookieOptions() {
  const secureOverride = process.env.COOKIE_SECURE?.trim().toLowerCase();
  return {
    httpOnly: true,
    sameSite: "lax" as const,
    path: "/",
    // Production defaults to HTTPS-only cookies. COOKIE_SECURE remains an
    // explicit override for local/LAN deployments that intentionally use HTTP.
    secure:
      secureOverride === "true" ||
      (secureOverride !== "false" && process.env.RAGGIE_ENV === "production"),
  };
}
