// SPDX-License-Identifier: Apache-2.0

import type { NextRequest } from "next/server";

import { withSameOrigin } from "@/lib/security/origin";
import { getFreshAccessToken } from "@/lib/session";

const CP_URL = process.env.CONTROL_PLANE_URL ?? "http://localhost:8000";

export const POST = withSameOrigin(async function POST(req: NextRequest) {
  const token = await getFreshAccessToken();
  if (!token) return new Response("unauthorized", { status: 401 });
  const res = await fetch(`${CP_URL}/api/v1/admin/branding/icon`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": req.headers.get("content-type") ?? "application/octet-stream",
    },
    body: await req.arrayBuffer(),
    cache: "no-store",
  });
  return new Response(res.body, {
    status: res.status,
    headers: { "Content-Type": "application/json" },
  });
});
