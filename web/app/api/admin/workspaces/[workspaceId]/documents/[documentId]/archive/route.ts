// SPDX-License-Identifier: Apache-2.0

import { type NextRequest } from "next/server";

import { withSameOrigin } from "@/lib/security/origin";
import { getFreshAccessToken } from "@/lib/session";

export const runtime = "nodejs";

const BASE = process.env.CONTROL_PLANE_URL ?? "http://localhost:8000";

// Archive a document: status → ARCHIVED + Qdrant chunks removed (object kept).
export const POST = withSameOrigin(async function POST(
  _req: NextRequest,
  { params }: { params: Promise<{ workspaceId: string; documentId: string }> },
) {
  const token = await getFreshAccessToken();
  if (!token) return new Response("unauthorized", { status: 401 });

  const { workspaceId, documentId } = await params;

  const res = await fetch(
    `${BASE}/api/v1/admin/workspaces/${workspaceId}/documents/${documentId}/archive`,
    {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
    },
  );

  return new Response(res.body, {
    status: res.status,
    headers: { "Content-Type": "application/json" },
  });
});
