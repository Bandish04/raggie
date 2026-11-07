// SPDX-License-Identifier: Apache-2.0

import { type NextRequest } from "next/server";

import { withSameOrigin } from "@/lib/security/origin";
import { getFreshAccessToken } from "@/lib/session";

export const runtime = "nodejs";

// Browser → this route → control-plane (Bearer added server-side).
const BASE = process.env.CONTROL_PLANE_URL ?? "http://localhost:8000";

// Create a resumable upload session.
export const POST = withSameOrigin(async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ workspaceId: string }> },
) {
  const token = await getFreshAccessToken();
  if (!token) return new Response("unauthorized", { status: 401 });

  const { workspaceId } = await params;
  const payload = await req.json().catch(() => ({}));

  const res = await fetch(
    `${BASE}/api/v1/admin/workspaces/${workspaceId}/documents/uploads`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
      cache: "no-store",
    },
  );

  // Retry-After rides along on a 503 (embedding profile not known yet).
  const retryAfter = res.headers.get("retry-after");
  return new Response(res.body, {
    status: res.status,
    headers: { "Content-Type": "application/json", ...(retryAfter ? { "Retry-After": retryAfter } : {}) },
  });
});
