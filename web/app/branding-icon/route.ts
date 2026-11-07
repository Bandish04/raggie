// SPDX-License-Identifier: Apache-2.0

import { type NextRequest, NextResponse } from "next/server";

import { decodeBrandIcon } from "@/lib/brand-icon";

const CP_URL = process.env.CONTROL_PLANE_URL ?? "http://localhost:8000";

// Serve the admin's uploaded brand icon as a REAL image URL (not a data: URL).
// Chrome silently ignores data: URIs in <link rel="icon"> and falls back to
// /favicon.ico — which is why favicon uploads appeared to do nothing. Here we
// decode the icon the control plane stores (returned as a data: URL by the
// public /branding endpoint) and stream the raw bytes with a proper
// Content-Type, so every browser honors it. The <link> carries a ?v= content
// hash (see app/layout.tsx) to bust the browser's sticky favicon cache.
export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  try {
    const res = await fetch(`${CP_URL}/api/v1/branding`, { cache: "no-store" });
    if (res.ok) {
      const b = (await res.json()) as { icon_data_url?: string | null };
      // Raster types only — an SVG is never served (see decodeBrandIcon).
      const icon = decodeBrandIcon(b.icon_data_url ?? "");
      if (icon) {
        return new NextResponse(new Uint8Array(icon.body), {
          status: 200,
          headers: {
            "Content-Type": icon.contentType,
            // Revalidate so a new upload is picked up; the ?v= hash does the
            // real cache-busting in browsers that over-cache favicons.
            "Cache-Control": "public, max-age=0, must-revalidate",
            // Admin-uploaded bytes on our origin: no sniffing into another
            // type, and inert (no script, no subresources) if opened directly.
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
          },
        });
      }
    }
  } catch {
    // Control plane unreachable / no icon — fall through to the default.
  }
  // No (raster) brand icon set → the bundled default favicon.
  return NextResponse.redirect(new URL("/favicon.ico", request.url), 302);
}
