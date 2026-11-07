// SPDX-License-Identifier: Apache-2.0

import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";

// Guard: untrusted markdown (model answers, widget-visitor conversations shown
// to admins) renders only through SafeMarkdown in answer-markdown.tsx, whose
// <img> path is markdownImageView (same-origin / inline raster only). A
// second react-markdown call site would come with react-markdown's default
// <img>, which fetches any URL the moment an admin opens the conversation.
const WEB = path.join(import.meta.dirname, "..", "..");
const SAFE = path.join("components", "chat", "answer-markdown.tsx");

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = path.join(dir, name);
    if (statSync(full).isDirectory()) return sources(full);
    return /\.(tsx?|mjs|js)$/.test(name) ? [full] : [];
  });
}

test("react-markdown is imported only by the safe markdown module", () => {
  const importers = ["app", "components", "lib"]
    .flatMap((d) => sources(path.join(WEB, d)))
    .filter((f) => /from\s+["']react-markdown["']/.test(readFileSync(f, "utf8")))
    .map((f) => path.relative(WEB, f));
  assert.deepEqual(importers, [SAFE]);
});

test("the safe module renders images only through markdownImageView", () => {
  const src = readFileSync(path.join(WEB, SAFE), "utf8");
  assert.match(src, /markdownImageView\(/);
  assert.match(src, /img:\s*\(props[^)]*\)\s*=>\s*\(\s*<MarkdownImage/);
  // Every <img> in the module takes its src from the view, never from props.
  const imgSrcs = [...src.matchAll(/<img\s+src=\{([^}]+)\}/g)].map((m) => m[1]);
  assert.ok(imgSrcs.length > 0);
  for (const s of imgSrcs) assert.equal(s, "view.src");
});

test("the admin conversation viewer uses SafeMarkdown", () => {
  const src = readFileSync(path.join(WEB, "components", "admin", "conversations-client.tsx"), "utf8");
  assert.match(src, /import\s+\{[^}]*\bSafeMarkdown\b[^}]*\}\s+from\s+"@\/components\/chat\/answer-markdown"/);
  assert.match(src, /<SafeMarkdown\b/);
});
