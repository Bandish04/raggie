// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from "next/server";

// Liveness/readiness probe target for k8s and the A1 time-to-login check.
export const dynamic = "force-dynamic";

export function GET() {
  return NextResponse.json({ status: "ok", service: "web" });
}
