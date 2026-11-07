// SPDX-License-Identifier: Apache-2.0

import type { NextRequest } from "next/server";

import { withSameOrigin } from "@/lib/security/origin";
import { getFreshAccessToken } from "@/lib/session";

const CP_URL = process.env.CONTROL_PLANE_URL ?? "http://localhost:8000";

// PUT branding text/color (JSON). Forwards to the control plane with the token.
export const PUT = withSameOrigin(async function PUT(req: NextRequest) {
  const token = await getFreshAccessToken();
  if (!token) return new Response("unauthorized", { status: 401 });
  const body = await req.text();
  const res = await fetch(`${CP_URL}/api/v1/admin/branding`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body,
    cache: "no-store",
  });
  return new Response(res.body, {
    status: res.status,
    headers: { "Content-Type": "application/json" },
  });
});
