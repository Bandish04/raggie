// SPDX-License-Identifier: Apache-2.0

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, test } from "node:test";

import { diffKeyPaths, findDuplicateKeys, keyPaths } from "./i18n-check.ts";

describe("findDuplicateKeys", () => {
  test("reports a key repeated inside the same object, with its path", () => {
    const src = '{"chat": {"a": "1", "b": "2", "a": "3"}, "admin": {"a": "x"}}';
    assert.deepEqual(findDuplicateKeys(src), ["chat.a"]);
  });

  test("the same key in different objects is fine", () => {
    assert.deepEqual(findDuplicateKeys('{"x": {"k": 1}, "y": {"k": 2}, "k": 3}'), []);
  });

  test("handles escapes, nested arrays and every JSON value type", () => {
    const src = '{"s": "q\\"uote \\\\ \\u00e7", "n": -1.5e3, "t": true, "f": false, "z": null, "arr": [{"d": 1, "d": 2}], "s": 0}';
    assert.deepEqual(findDuplicateKeys(src), ["arr[0].d", "s"]);
  });

  test("rejects malformed JSON", () => {
    assert.throws(() => findDuplicateKeys('{"a": 1,}'));
    assert.throws(() => findDuplicateKeys('{"a": 1'));
  });
});

describe("keyPaths / diffKeyPaths", () => {
  test("flattens leaf paths", () => {
    assert.deepEqual(keyPaths({ a: { b: "1", c: { d: "2" } }, e: "3" }), ["a.b", "a.c.d", "e"]);
  });

  test("reports paths missing on either side, not just count differences", () => {
    // Same count (2 leaves each) but different key sets.
    const diff = diffKeyPaths({ a: "1", b: "2" }, { a: "1", c: "2" });
    assert.deepEqual(diff, { onlyInFirst: ["b"], onlyInSecond: ["c"] });
  });
});

// The real catalogs: no duplicate keys, and identical key paths in tr and en.
describe("messages catalogs", () => {
  const dir = path.join(import.meta.dirname, "..", "messages");
  const read = (l: string) => readFileSync(path.join(dir, `${l}.json`), "utf8");

  for (const locale of ["en", "tr","de"]) {
    test(`${locale}.json has no duplicate keys`, () => {
      assert.deepEqual(findDuplicateKeys(read(locale)), []);
    });
  }

  for (const locale of ["tr", "de"]) {
  test(`${locale}.json and en.json have the same key paths`, () => {
    const diff = diffKeyPaths(JSON.parse(read("en")), JSON.parse(read(locale)));
    assert.deepEqual(
      diff,
      { onlyInFirst: [], onlyInSecond: [] },
      `onlyInFirst = en only, onlyInSecond = ${locale} only`,
    );
  });
}
   
});
