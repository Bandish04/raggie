// SPDX-License-Identifier: Apache-2.0

// CSRF defence for the /api route handlers: a mutating request must come from
// the app's own origin. Browsers always send `Origin` on cross-site (and
// same-origin) POST/PUT/PATCH/DELETE fetches, and a cross-site page cannot
// forge it or the Host / X-Forwarded-Host headers it is compared against.
//
// Server actions are not covered here: Next.js applies the same check to them.
//
// Pure (no next/* imports) so it can be unit-tested with node:test.

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

function firstValue(v: string | null): string | null {
  const first = v?.split(",")[0]?.trim();
  return first || null;
}

function hostOf(url: string): string | null {
  try {
    return new URL(url).host.toLowerCase();
  } catch {
    return null;
  }
}

/** Hosts (host[:port]) the app is legitimately served from: the forwarded or
 *  direct Host header, the request URL, plus every origin in PUBLIC_WEB_URL
 *  (comma-separated) for deployments behind a proxy that rewrites Host. */
function allowedHosts(requestUrl: string, headers: Headers, publicWebUrl: string | undefined): Set<string> {
  const hosts = new Set<string>();
  const add = (h: string | null) => h && hosts.add(h.toLowerCase());
  add(firstValue(headers.get("x-forwarded-host")));
  add(firstValue(headers.get("host")));
  add(hostOf(requestUrl));
  for (const u of (publicWebUrl ?? "").split(",")) {
    if (u.trim()) add(hostOf(u.trim()));
  }
  return hosts;
}

/** True when the request may proceed: a safe method, or a mutating method whose
 *  Origin (Referer as a fallback) points at one of the app's own hosts. A
 *  mutating request with neither header, or with the opaque "null" origin, is
 *  rejected. */
export function isSameOriginRequest(
  method: string,
  requestUrl: string,
  headers: Headers,
  publicWebUrl: string | undefined = process.env.PUBLIC_WEB_URL,
): boolean {
  if (SAFE_METHODS.has(method.toUpperCase())) return true;
  const origin = headers.get("origin");
  if (origin === "null") return false;
  const source = origin ?? headers.get("referer");
  if (!source) return false;
  const sourceHost = hostOf(source);
  return !!sourceHost && allowedHosts(requestUrl, headers, publicWebUrl).has(sourceHost);
}

/** Wraps a route handler so cross-origin mutating requests get a 403 JSON
 *  response before the handler (and any upstream call) runs. Route context
 *  (`{ params }`) is passed through unchanged. */
export function withSameOrigin<R extends Request, A extends unknown[]>(
  handler: (req: R, ...rest: A) => Response | Promise<Response>,
): (req: R, ...rest: A) => Promise<Response> {
  return async (req, ...rest) => {
    if (!isSameOriginRequest(req.method, req.url, req.headers)) {
      return Response.json({ detail: "Cross-origin request rejected" }, { status: 403 });
    }
    return handler(req, ...rest);
  };
}
