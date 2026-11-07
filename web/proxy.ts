// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { refreshSession, tokenExpiresWithin } from "@/lib/auth-refresh";
import { forwardedHeaders } from "@/lib/security/forwarded";
import {
  ACCESS_COOKIE,
  ACCESS_MAX_AGE,
  REFRESH_COOKIE,
  REFRESH_MAX_AGE,
  REFRESH_SKEW_SECONDS,
  sessionCookieOptions,
} from "@/lib/session-cookies";

const PROTECTED_PREFIXES = ["/dashboard", "/admin", "/chat"];

function isProtected(pathname: string): boolean {
  return PROTECTED_PREFIXES.some((p) => pathname === p || pathname.startsWith(`${p}/`));
}

// Auth gate (Next.js 16 proxy convention): redirect to /login when no access
// cookie is present. Onboarding is intentionally public (first-run setup happens
// before any account exists).
//
// Session refresh: when the access token is missing or about to expire and a
// refresh cookie exists, rotate it here — before any server component reads
// the token — via the single-flight refresher (lib/auth-refresh), then hand the
// new cookies both to this request and to the browser. An "invalid" refresh
// (expired / revoked / reused) clears both cookies, so the next request goes
// straight to /login instead of retrying in a loop.
//
// Also adds HSTS when ENABLE_HSTS=true. It lives here rather than in
// next.config headers() because those are fixed at build time, while this reads
// the env at runtime (so a prebuilt image can turn it on). Only enable it when
// the app is served over HTTPS; browsers ignore the header on plain HTTP.
export async function proxy(req: NextRequest) {
  let access = req.cookies.get(ACCESS_COOKIE)?.value;
  const refresh = req.cookies.get(REFRESH_COOKIE)?.value;
  let rotated: { access_token: string; refresh_token: string } | null = null;
  let clearCookies = false;

  if (refresh && (!access || tokenExpiresWithin(access, REFRESH_SKEW_SECONDS))) {
    const outcome = await refreshSession(refresh, forwardedHeaders(req.headers));
    if (outcome.ok) {
      rotated = outcome.tokens;
      access = rotated.access_token;
      // Visible to server components/actions rendering this same request.
      req.cookies.set(ACCESS_COOKIE, rotated.access_token);
      req.cookies.set(REFRESH_COOKIE, rotated.refresh_token);
    } else if (outcome.reason === "invalid") {
      clearCookies = true;
      access = undefined;
      req.cookies.delete(ACCESS_COOKIE);
      req.cookies.delete(REFRESH_COOKIE);
    }
    // "unavailable": keep the cookies untouched and retry on a later request.
  }

  let res: NextResponse;
  if (isProtected(req.nextUrl.pathname) && !access) {
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    res = NextResponse.redirect(url);
  } else {
    res = NextResponse.next({ request: { headers: req.headers } });
  }

  if (rotated) {
    const opts = sessionCookieOptions();
    res.cookies.set(ACCESS_COOKIE, rotated.access_token, { ...opts, maxAge: ACCESS_MAX_AGE });
    res.cookies.set(REFRESH_COOKIE, rotated.refresh_token, { ...opts, maxAge: REFRESH_MAX_AGE });
  } else if (clearCookies) {
    res.cookies.delete(ACCESS_COOKIE);
    res.cookies.delete(REFRESH_COOKIE);
  }
  if (process.env.ENABLE_HSTS === "true") {
    res.headers.set("Strict-Transport-Security", "max-age=31536000");
  }
  return res;
}

export const config = {
  matcher: [
    // Auth-gated sections (every request, as before).
    "/dashboard/:path*",
    "/admin/:path*",
    "/chat/:path*",
    // Every other page, for session refresh + HSTS. Excludes /api (proxying
    // would buffer request bodies, e.g. upload parts — route handlers refresh
    // via getFreshAccessToken), static assets, and server-action POSTs.
    {
      source: "/((?!api/|_next/static|_next/image|fonts/|favicon.ico|healthz).*)",
      missing: [{ type: "header", key: "next-action" }],
    },
  ],
};
