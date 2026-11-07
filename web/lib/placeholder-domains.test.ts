// SPDX-License-Identifier: Apache-2.0

import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";

// Sample addresses in UI copy and placeholders use RFC 2606 reserved domains
// (example.com/.org/.net, *.example, *.test, *.invalid, *.localhost), never a
// domain someone could register or already owns.
const WEB = path.join(import.meta.dirname, "..");
const EMAIL = /[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})/g;
const RESERVED = /^(?:(?:[a-z0-9-]+\.)*example\.(?:com|org|net)|(?:[a-z0-9-]+\.)+(?:example|test|invalid|localhost))$/i;

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = path.join(dir, name);
    if (statSync(full).isDirectory()) return files(full);
    return /\.(json|tsx?)$/.test(name) && !name.endsWith(".test.ts") ? [full] : [];
  });
}

test("placeholder emails use reserved example domains", () => {
  const offenders = ["messages", "components", "app"]
    .flatMap((d) => files(path.join(WEB, d)))
    .flatMap((f) =>
      [...readFileSync(f, "utf8").matchAll(EMAIL)]
        .filter((m) => !RESERVED.test(m[1]))
        .map((m) => `${path.relative(WEB, f)}: ${m[0]}`),
    );
  assert.deepEqual(offenders, []);
});
