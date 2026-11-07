// SPDX-License-Identifier: Apache-2.0

import type { NextRequest } from "next/server";

import { getFreshAccessToken } from "@/lib/session";

const EDGE_URL = process.env.EDGE_URL ?? "http://localhost:8080";

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const token = await getFreshAccessToken();
  if (!token) return new Response("unauthorized", { status: 401 });
  const { id } = await params;
  const res = await fetch(
    `${EDGE_URL}/api/v1/admin/conversations/${encodeURIComponent(id)}/messages`,
    { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" },
  );
  return new Response(res.body, {
    status: res.status,
    headers: { "Content-Type": "application/json" },
  });
}
