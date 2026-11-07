// SPDX-License-Identifier: Apache-2.0

import { getFreshAccessToken } from "@/lib/session";

// Admin-only proxy that asks the Go edge for canonical models plus non-secret
// provider/capability metadata. Provider keys remain server-side in edge env.
const EDGE_URL = process.env.EDGE_URL ?? "http://localhost:8080";

export async function GET() {
  const token = await getFreshAccessToken();
  if (!token) {
    return Response.json({ models: [] }, { status: 401 });
  }
  try {
    const res = await fetch(`${EDGE_URL}/api/v1/models`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
    });
    if (!res.ok) {
      return Response.json({ models: [] }, { status: res.status });
    }
    return Response.json(await res.json());
  } catch {
    return Response.json({ models: [] }, { status: 200 });
  }
}
