// SPDX-License-Identifier: Apache-2.0

import { getFreshAccessToken } from "@/lib/session";

export const runtime = "nodejs";

// Same-origin read of the embedding profile status for the admin card's
// re-embed progress polling. The control plane enforces platform admin.
const BASE = process.env.CONTROL_PLANE_URL ?? "http://localhost:8000";

export async function GET() {
  const token = await getFreshAccessToken();
  if (!token) return Response.json({ error: "unauthorized" }, { status: 401 });
  try {
    const res = await fetch(`${BASE}/api/v1/admin/embeddings`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
    });
    return new Response(res.body, {
      status: res.status,
      headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
    });
  } catch {
    return Response.json({ error: "unavailable" }, { status: 502 });
  }
}
