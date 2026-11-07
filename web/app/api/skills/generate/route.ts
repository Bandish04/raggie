// SPDX-License-Identifier: Apache-2.0

import type { NextRequest } from "next/server";

import { withSameOrigin } from "@/lib/security/origin";
import { getFreshAccessToken } from "@/lib/session";
import { uiLocale } from "@/lib/ui-locale";

// Same-origin proxy: the skill modals POST { description } here; we forward to the
// Go edge (which holds the LLM) and relay the { instructions } JSON back. Mirrors
// the /api/chat proxy. The edge AI-generates a skill system prompt from a short
// description.
const EDGE_URL = process.env.EDGE_URL ?? "http://localhost:8080";

export const POST = withSameOrigin(async function POST(req: NextRequest) {
  const token = await getFreshAccessToken();
  if (!token) return Response.json({ error: "unauthorized", code: "unauthorized" }, { status: 401 });
  const body = await req.text();
  try {
    const res = await fetch(`${EDGE_URL}/api/v1/skills/generate-instructions`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
        // Edge error `message` in the UI language (the UI translates `code`).
        "Accept-Language": uiLocale(req.cookies.get("NEXT_LOCALE")?.value),
      },
      body,
      cache: "no-store",
    });
    return new Response(res.body, {
      status: res.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch {
    // Edge unreachable: the edge error envelope; the UI picks the text by code.
    return Response.json({ error: "internal_error", code: "internal_error" }, { status: 502 });
  }
});
