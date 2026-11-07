// SPDX-License-Identifier: Apache-2.0

import { type NextRequest } from "next/server";

import { withSameOrigin } from "@/lib/security/origin";
import { getFreshAccessToken } from "@/lib/session";

export const runtime = "nodejs";

const BASE = process.env.CONTROL_PLANE_URL ?? "http://localhost:8000";

// Upload a single part (raw binary body) for a resumable upload session.
export const PUT = withSameOrigin(async function PUT(
  req: NextRequest,
  { params }: { params: Promise<{ workspaceId: string }> },
) {
  const token = await getFreshAccessToken();
  if (!token) return new Response("unauthorized", { status: 401 });

  const { workspaceId } = await params;

  const uploadId = req.headers.get("x-upload-id");
  const objectKey = req.headers.get("x-object-key");
  const partNumber = req.headers.get("x-part-number");
  if (!uploadId || !objectKey || !partNumber) {
    return new Response("missing upload headers", { status: 400 });
  }

  // A part is bounded by part_size, so reading it fully is safe.
  const body = await req.arrayBuffer();

  const res = await fetch(
    `${BASE}/api/v1/admin/workspaces/${workspaceId}/documents/uploads/parts`,
    {
      method: "PUT",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/octet-stream",
        "X-Upload-Id": uploadId,
        "X-Object-Key": objectKey,
        "X-Part-Number": partNumber,
      },
      body,
      cache: "no-store",
    },
  );

  return new Response(res.body, {
    status: res.status,
    headers: { "Content-Type": "application/json" },
  });
});
