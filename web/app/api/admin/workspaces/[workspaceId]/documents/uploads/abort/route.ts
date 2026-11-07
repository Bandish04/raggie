// SPDX-License-Identifier: Apache-2.0

import { type NextRequest } from "next/server";

import { withSameOrigin } from "@/lib/security/origin";
import { getFreshAccessToken } from "@/lib/session";

export const runtime = "nodejs";

const BASE = process.env.CONTROL_PLANE_URL ?? "http://localhost:8000";

// Abort an in-flight resumable upload session.
export const POST = withSameOrigin(async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ workspaceId: string }> },
) {
  const token = await getFreshAccessToken();
  if (!token) return new Response("unauthorized", { status: 401 });

  const { workspaceId } = await params;
  const payload = await req.json().catch(() => ({}));

  const res = await fetch(
    `${BASE}/api/v1/admin/workspaces/${workspaceId}/documents/uploads/abort`,
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

  // Abort returns 204 (no body). Mirror the status code.
  return new Response(null, { status: res.status });
});
