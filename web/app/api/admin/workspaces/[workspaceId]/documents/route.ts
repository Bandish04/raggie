// SPDX-License-Identifier: Apache-2.0

import { type NextRequest } from "next/server";

import { getFreshAccessToken } from "@/lib/session";

export const runtime = "nodejs";

const BASE = process.env.CONTROL_PLANE_URL ?? "http://localhost:8000";

// List documents for a workspace (used by the KB client for live status polling
// and Drive folder navigation). Forwards an optional ?folder_id= scope filter.
export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ workspaceId: string }> },
) {
  const token = await getFreshAccessToken();
  if (!token) return new Response("unauthorized", { status: 401 });

  const { workspaceId } = await params;
  const folderId = req.nextUrl.searchParams.get("folder_id");
  const qs = folderId ? `?folder_id=${encodeURIComponent(folderId)}` : "";

  const res = await fetch(
    `${BASE}/api/v1/admin/workspaces/${workspaceId}/documents${qs}`,
    {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
    },
  );

  return new Response(res.body, {
    status: res.status,
    headers: { "Content-Type": "application/json" },
  });
}
