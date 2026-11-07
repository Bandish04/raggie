// SPDX-License-Identifier: Apache-2.0

import { type NextRequest } from "next/server";

import { withSameOrigin } from "@/lib/security/origin";
import { getFreshAccessToken } from "@/lib/session";

export const runtime = "nodejs";

const BASE = process.env.CONTROL_PLANE_URL ?? "http://localhost:8000";

// List every folder in a workspace (flat; the client builds the tree from
// parent_folder_id).
export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ workspaceId: string }> },
) {
  const token = await getFreshAccessToken();
  if (!token) return new Response("unauthorized", { status: 401 });

  const { workspaceId } = await params;

  const res = await fetch(
    `${BASE}/api/v1/admin/workspaces/${workspaceId}/folders`,
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

// Create a folder (body {name, parent_folder_id?}).
export const POST = withSameOrigin(async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ workspaceId: string }> },
) {
  const token = await getFreshAccessToken();
  if (!token) return new Response("unauthorized", { status: 401 });

  const { workspaceId } = await params;
  const payload = await req.json().catch(() => ({}));

  const res = await fetch(
    `${BASE}/api/v1/admin/workspaces/${workspaceId}/folders`,
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

  return new Response(res.body, {
    status: res.status,
    headers: { "Content-Type": "application/json" },
  });
});
