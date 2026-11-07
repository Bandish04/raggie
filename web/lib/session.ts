// SPDX-License-Identifier: Apache-2.0

import "server-only";

import { cookies, headers } from "next/headers";

import type { Tokens } from "@/lib/api";
import { refreshSession, tokenExpiresWithin } from "@/lib/auth-refresh";
import { forwardedHeaders } from "@/lib/security/forwarded";
import {
  ACCESS_COOKIE as ACCESS,
  ACCESS_MAX_AGE,
  REFRESH_COOKIE as REFRESH,
  REFRESH_MAX_AGE,
  REFRESH_SKEW_SECONDS,
  sessionCookieOptions,
} from "@/lib/session-cookies";

export async function setSession(tokens: Tokens): Promise<void> {
  const store = await cookies();
  const opts = sessionCookieOptions();
  store.set(ACCESS, tokens.access_token, { ...opts, maxAge: ACCESS_MAX_AGE });
  store.set(REFRESH, tokens.refresh_token, { ...opts, maxAge: REFRESH_MAX_AGE });
}

export async function getAccessToken(): Promise<string | null> {
  return (await cookies()).get(ACCESS)?.value ?? null;
}

/** Like getAccessToken, but refreshes an expired / about-to-expire access token
 *  (single-flight, see lib/auth-refresh) and persists the rotated cookies.
 *
 *  Only call where cookies can be written — route handlers and server actions.
 *  Server components must use getAccessToken: rotating the refresh token there
 *  without persisting the new cookie would make the browser replay the old
 *  one, which the control plane treats as reuse and revokes the session. (Page
 *  navigations are refreshed earlier, in proxy.ts.) */
export async function getFreshAccessToken(): Promise<string | null> {
  const store = await cookies();
  const access = store.get(ACCESS)?.value ?? null;
  const refresh = store.get(REFRESH)?.value;
  if (!refresh || (access && !tokenExpiresWithin(access, REFRESH_SKEW_SECONDS))) return access;
  const outcome = await refreshSession(refresh, await requestForwardedHeaders());
  if (outcome.ok) {
    await setSession(outcome.tokens);
    return outcome.tokens.access_token;
  }
  if (outcome.reason === "invalid") {
    // Session is over upstream; drop the cookies so we do not retry it.
    await clearSession();
    return null;
  }
  // Control plane unreachable: keep the cookies, let the caller fail normally.
  return access;
}

/** X-Forwarded-For / -Proto for the current request (empty outside one), so
 *  upstream rate limits and audit logs see the end user's IP. */
export async function requestForwardedHeaders(): Promise<Record<string, string>> {
  try {
    return forwardedHeaders(await headers());
  } catch {
    return {};
  }
}

export async function clearSession(): Promise<void> {
  const store = await cookies();
  store.delete(ACCESS);
  store.delete(REFRESH);
}
