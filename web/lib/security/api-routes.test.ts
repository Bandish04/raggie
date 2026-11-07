// SPDX-License-Identifier: Apache-2.0

import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";

// Guard: every mutating route handler under app/api must be wrapped in
// withSameOrigin (CSRF origin check), so a newly added handler cannot silently
// skip it. Handlers are found by their exported method name.
const API_DIR = path.join(import.meta.dirname, "..", "..", "app", "api");

function routeFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = path.join(dir, name);
    if (statSync(full).isDirectory()) return routeFiles(full);
    return name === "route.ts" ? [full] : [];
  });
}

const MUTATING = new Set(["POST", "PUT", "PATCH", "DELETE"]);

// Mutating handlers exported by one route module, and whether each is wrapped.
// Covers `export async function POST`, `export const POST = …` and export
// lists (`export { handler as DELETE }`, `export { POST }`), where the local
// binding must itself be `const <name> = withSameOrigin(…)`.
function mutatingHandlers(src: string): { method: string; wrapped: boolean }[] {
  const out: { method: string; wrapped: boolean }[] = [];
  const isWrappedConst = (name: string) =>
    new RegExp(`\\bconst\\s+${name}\\s*(?::[^=]+)?=\\s*withSameOrigin\\(`).test(src);
  for (const m of src.matchAll(/export\s+(async\s+function|function|const|let|var)\s+(\w+)\b([^\n]*)/g)) {
    const [, kind, method, rest] = m;
    if (!MUTATING.has(method)) continue;
    out.push({ method, wrapped: kind === "const" && /=\s*withSameOrigin\(/.test(rest) });
  }
  for (const m of src.matchAll(/export\s*(?:type\s*)?\{([^}]*)\}/g)) {
    for (const spec of m[1].split(",")) {
      const parts = spec.trim().match(/^(?:type\s+)?(\w+)(?:\s+as\s+(\w+))?$/);
      if (!parts) continue;
      const [, local, exported = local] = parts;
      if (MUTATING.has(exported)) out.push({ method: exported, wrapped: isWrappedConst(local) });
    }
  }
  return out;
}

test("mutatingHandlers: direct exports", () => {
  assert.deepEqual(mutatingHandlers("export async function POST(req) {}"), [{ method: "POST", wrapped: false }]);
  assert.deepEqual(mutatingHandlers("export const DELETE = withSameOrigin(async () => {});"), [
    { method: "DELETE", wrapped: true },
  ]);
  assert.deepEqual(mutatingHandlers("export const PUT = async () => {};"), [{ method: "PUT", wrapped: false }]);
  assert.deepEqual(mutatingHandlers("export async function GET() {}"), []);
});

test("mutatingHandlers: export lists and aliases", () => {
  assert.deepEqual(mutatingHandlers("async function remove() {}\nexport { remove as DELETE };"), [
    { method: "DELETE", wrapped: false },
  ]);
  assert.deepEqual(mutatingHandlers("const remove = withSameOrigin(async () => {});\nexport { remove as DELETE };"), [
    { method: "DELETE", wrapped: true },
  ]);
  assert.deepEqual(mutatingHandlers("function POST() {}\nexport { GET, POST };"), [{ method: "POST", wrapped: false }]);
  assert.deepEqual(
    mutatingHandlers("const h = withSameOrigin(x);\nasync function p() {}\nexport {\n  h as PATCH,\n  p as PUT,\n};"),
    [
      { method: "PATCH", wrapped: true },
      { method: "PUT", wrapped: false },
    ],
  );
  // Aliasing away from a method name exports nothing mutating.
  assert.deepEqual(mutatingHandlers("const POST = 1;\nexport { POST as notAHandler };"), []);
});

test("every mutating /api handler is wrapped in withSameOrigin", () => {
  const files = routeFiles(API_DIR);
  assert.ok(files.length > 0, "no route handlers found");
  const offenders: string[] = [];
  let wrapped = 0;
  for (const file of files) {
    for (const h of mutatingHandlers(readFileSync(file, "utf8"))) {
      if (h.wrapped) wrapped += 1;
      else offenders.push(`${path.relative(API_DIR, file)} ${h.method}`);
    }
  }
  assert.deepEqual(offenders, [], `unguarded mutating handlers:\n${offenders.join("\n")}`);
  assert.ok(wrapped > 0);
});
