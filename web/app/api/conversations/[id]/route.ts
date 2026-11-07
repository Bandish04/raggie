// SPDX-License-Identifier: Apache-2.0

import type { NextRequest } from "next/server";

import { withSameOrigin } from "@/lib/security/origin";
import { getFreshAccessToken } from "@/lib/session";

// Deletes one of the user's conversations and its messages. The edge enforces
// ownership (a user can only delete their own); mirrors the other /api proxies.
const EDGE_URL = process.env.EDGE_URL ?? "http://localhost:8080";

export const DELETE = withSameOrigin(async function DELETE(_req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const token = await getFreshAccessToken();
  if (!token) return new Response("unauthorized", { status: 401 });
  const { id } = await params;
  const res = await fetch(`${EDGE_URL}/api/v1/conversations/${encodeURIComponent(id)}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  return new Response(res.body, { status: res.status });
});
