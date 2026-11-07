// SPDX-License-Identifier: Apache-2.0

import type { NextRequest } from "next/server";

import { getFreshAccessToken } from "@/lib/session";

// Admin oversight proxy: forwards to the Go edge (which authorizes the admin and
// scopes by workspace). Mirrors /api/conversations but hits the admin endpoint.
const EDGE_URL = process.env.EDGE_URL ?? "http://localhost:8080";

export async function GET(req: NextRequest) {
  const token = await getFreshAccessToken();
  if (!token) return new Response("unauthorized", { status: 401 });
  const search = new URL(req.url).search;
  const res = await fetch(`${EDGE_URL}/api/v1/admin/conversations${search}`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  return new Response(res.body, {
    status: res.status,
    headers: { "Content-Type": "application/json" },
  });
}
