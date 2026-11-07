// SPDX-License-Identifier: Apache-2.0

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";

// The updates card links to release_url from a remote manifest: it must pass
// safeHttpsHref, never be used as an href directly.
const WEB = path.join(import.meta.dirname, "..", "..");

test("updates card links release_url only through safeHttpsHref", () => {
  const src = readFileSync(path.join(WEB, "components", "admin", "updates-client.tsx"), "utf8");
  assert.doesNotMatch(src, /href=\{status\.release_url\}/);
  assert.match(src, /safeHttpsHref\(status\.release_url\)/);
});
