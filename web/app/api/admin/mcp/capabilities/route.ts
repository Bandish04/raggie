// SPDX-License-Identifier: Apache-2.0

import type { NextRequest } from "next/server";

import { getFreshAccessToken } from "@/lib/session";

// Admin MCP capability proxy: forwards to the Go edge (which authorizes the admin
// and probes the live MCP session). Mirrors /api/admin/conversations. The edge
// endpoint is fail-soft (always 200 with a status field), so we just pass through.
const EDGE_URL = process.env.EDGE_URL ?? "http://localhost:8080";

export async function GET(req: NextRequest) {
  const token = await getFreshAccessToken();
  if (!token) return new Response("unauthorized", { status: 401 });
  const search = new URL(req.url).search;
  const res = await fetch(`${EDGE_URL}/api/v1/admin/mcp/capabilities${search}`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  return new Response(res.body, {
    status: res.status,
    headers: { "Content-Type": "application/json" },
  });
}
