// SPDX-License-Identifier: Apache-2.0

import type { NextRequest } from "next/server";

import { withSameOrigin } from "@/lib/security/origin";
import { getFreshAccessToken } from "@/lib/session";

// Lists the signed-in user's conversations (chat history). Proxies to the edge
// server-side, attaching the session token (mirrors /api/chat).
const EDGE_URL = process.env.EDGE_URL ?? "http://localhost:8080";

export async function GET(req: NextRequest) {
  const token = await getFreshAccessToken();
  if (!token) return new Response("unauthorized", { status: 401 });
  const limit = req.nextUrl.searchParams.get("limit") ?? "30";
  const res = await fetch(`${EDGE_URL}/api/v1/conversations?limit=${encodeURIComponent(limit)}`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  return new Response(res.body, {
    status: res.status,
    headers: { "Content-Type": "application/json" },
  });
}

// Clears the signed-in user's entire chat history (edge enforces ownership).
export const DELETE = withSameOrigin(async function DELETE() {
  const token = await getFreshAccessToken();
  if (!token) return new Response("unauthorized", { status: 401 });
  const res = await fetch(`${EDGE_URL}/api/v1/conversations`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  return new Response(res.body, {
    status: res.status,
    headers: { "Content-Type": "application/json" },
  });
});
