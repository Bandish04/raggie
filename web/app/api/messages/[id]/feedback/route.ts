// SPDX-License-Identifier: Apache-2.0

import type { NextRequest } from "next/server";

import { withSameOrigin } from "@/lib/security/origin";
import { getFreshAccessToken } from "@/lib/session";

// Records 👍/👎 on a BOT message. Proxies to the edge (which enforces that only
// the conversation owner may rate).
const EDGE_URL = process.env.EDGE_URL ?? "http://localhost:8080";

export const POST = withSameOrigin(async function POST(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const token = await getFreshAccessToken();
  if (!token) return new Response("unauthorized", { status: 401 });
  const { id } = await params;
  const body = await req.text();
  const res = await fetch(
    `${EDGE_URL}/api/v1/messages/${encodeURIComponent(id)}/feedback`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body,
      cache: "no-store",
    },
  );
  return new Response(null, { status: res.status });
});
