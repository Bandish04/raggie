// SPDX-License-Identifier: Apache-2.0

import { type NextRequest } from "next/server";

import { withSameOrigin } from "@/lib/security/origin";
import { getFreshAccessToken } from "@/lib/session";

export const runtime = "nodejs";

const BASE = process.env.CONTROL_PLANE_URL ?? "http://localhost:8000";

// Rename and/or move a folder (body {name?, parent_folder_id?}).
export const PATCH = withSameOrigin(async function PATCH(
  req: NextRequest,
  { params }: { params: Promise<{ workspaceId: string; folderId: string }> },
) {
  const token = await getFreshAccessToken();
  if (!token) return new Response("unauthorized", { status: 401 });

  const { workspaceId, folderId } = await params;
  const payload = await req.json().catch(() => ({}));

  const res = await fetch(
    `${BASE}/api/v1/admin/workspaces/${workspaceId}/folders/${folderId}`,
    {
      method: "PATCH",
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

// Recursively delete a folder (sub-folders + their documents are purged server-side).
export const DELETE = withSameOrigin(async function DELETE(
  _req: NextRequest,
  { params }: { params: Promise<{ workspaceId: string; folderId: string }> },
) {
  const token = await getFreshAccessToken();
  if (!token) return new Response("unauthorized", { status: 401 });

  const { workspaceId, folderId } = await params;

  const res = await fetch(
    `${BASE}/api/v1/admin/workspaces/${workspaceId}/folders/${folderId}`,
    {
      method: "DELETE",
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
    },
  );

  return new Response(res.body, { status: res.status });
});
