// SPDX-License-Identifier: Apache-2.0

import { withSameOrigin } from "@/lib/security/origin";
import { getFreshAccessToken } from "@/lib/session";

export const runtime = "nodejs";

const CP_URL = process.env.CONTROL_PLANE_URL ?? "http://localhost:8000";

// Re-enqueue every FAILED document in the org (super-admin). Forwards to the
// control plane with the caller's token.
export const POST = withSameOrigin(async function POST() {
  const token = await getFreshAccessToken();
  if (!token) return new Response("unauthorized", { status: 401 });

  const res = await fetch(`${CP_URL}/api/v1/admin/documents/retry-failed`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });

  return new Response(res.body, {
    status: res.status,
    headers: { "Content-Type": "application/json" },
  });
});
