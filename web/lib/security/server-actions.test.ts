// SPDX-License-Identifier: Apache-2.0

import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";

// Guard: server actions must authenticate with getFreshAccessToken, never the
// raw cookie read (getAccessToken). Actions can write cookies, so they refresh
// an expired access token and persist the rotation; the raw read would send an
// expired token and fail a save with 401/403 right at expiry. (Server
// components keep getAccessToken: they cannot persist a rotated cookie.)
const ROOTS = ["app", "components", "lib"].map((d) => path.join(import.meta.dirname, "..", "..", d));

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = path.join(dir, name);
    if (statSync(full).isDirectory()) return name === "node_modules" ? [] : sourceFiles(full);
    return /\.tsx?$/.test(name) && !name.endsWith(".test.ts") ? [full] : [];
  });
}

// The directive must be the first statement; license headers and other
// leading comments may precede it.
const LEADING_COMMENTS = /^(?:\s+|\/\/[^\n]*|\/\*[\s\S]*?\*\/)*/;
const isServerActionModule = (src: string) =>
  /^(["'])use server\1/.test(src.replace(LEADING_COMMENTS, ""));

test("server actions use getFreshAccessToken, not getAccessToken", () => {
  const files = ROOTS.flatMap(sourceFiles).filter((f) => isServerActionModule(readFileSync(f, "utf8")));
  assert.ok(files.length > 0, "no server action modules found");
  const offenders = files
    .filter((f) => /\bgetAccessToken\s*\(/.test(readFileSync(f, "utf8")))
    .map((f) => path.relative(path.join(import.meta.dirname, "..", ".."), f));
  assert.deepEqual(offenders, [], `server actions reading the raw access token:\n${offenders.join("\n")}`);
});

test("no inline 'use server' functions outside action modules", () => {
  // Inline actions inside server components would escape the guard above.
  const offenders = ROOTS.flatMap(sourceFiles).filter((f) => {
    const src = readFileSync(f, "utf8");
    return !isServerActionModule(src) && /\n\s*(["'])use server\1/.test(src);
  });
  assert.deepEqual(offenders, []);
});
