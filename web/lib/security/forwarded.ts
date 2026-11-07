// SPDX-License-Identifier: Apache-2.0

import { isIP } from "node:net";

// Forward the end user's IP and protocol on server-side calls to the control
// plane / edge, so per-client rate limits and audit logs see the real client
// instead of the web container. Upstreams trust these headers only from
// private/loopback peers (this web tier).
//
// Where the chain comes from: Next's server sets `x-forwarded-for` to the
// socket peer when the incoming request has none, and otherwise keeps the
// chain an upstream reverse proxy built (app code cannot read the socket
// address itself). Upstreams walk the chain right-to-left skipping trusted
// hops, so a client-supplied left-most entry is ignored whenever a reverse
// proxy appends the real peer. Exposed directly to untrusted clients, put a
// proxy in front that sets X-Forwarded-For.
//
// Pure (no next/* imports): callable from proxy.ts, route handlers and server
// actions, and unit-testable with node:test.

// Right-most hops are the ones our own proxies appended; cap the chain so a
// client cannot ship an arbitrarily long header upstream.
const MAX_HOPS = 16;

function normaliseHop(raw: string): string | null {
  let hop = raw.trim();
  const bracketed = hop.match(/^\[([^\]]+)\](?::\d+)?$/);
  if (bracketed) hop = bracketed[1];
  else if (/^\d{1,3}(?:\.\d{1,3}){3}:\d+$/.test(hop)) hop = hop.slice(0, hop.lastIndexOf(":"));
  return isIP(hop) ? hop : null;
}

export function forwardedHeaders(incoming: Headers): Record<string, string> {
  const out: Record<string, string> = {};
  const chain = (incoming.get("x-forwarded-for") ?? "")
    .split(",")
    .map(normaliseHop)
    .filter((h): h is string => h !== null)
    .slice(-MAX_HOPS);
  if (chain.length) out["X-Forwarded-For"] = chain.join(", ");
  const proto = incoming.get("x-forwarded-proto")?.split(",")[0]?.trim().toLowerCase();
  if (proto === "http" || proto === "https") out["X-Forwarded-Proto"] = proto;
  return out;
}
