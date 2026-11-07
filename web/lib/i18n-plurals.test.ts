// SPDX-License-Identifier: Apache-2.0

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";

// Counts in UI strings use ICU plurals, not "(s)".
const load = (l: string) => JSON.parse(readFileSync(path.join(import.meta.dirname, "..", "messages", `${l}.json`), "utf8"));

test("kbItemCount pluralizes folders and documents", async () => {
  const { createTranslator } = await import("next-intl");
  const en = createTranslator({ locale: "en", messages: load("en"), namespace: "admin" });
  const tr = createTranslator({ locale: "tr", messages: load("tr"), namespace: "admin" });
  assert.equal(en("kbItemCount", { folders: 1, documents: 6 }), "1 folder · 6 documents");
  assert.equal(en("kbItemCount", { folders: 6, documents: 1 }), "6 folders · 1 document");
  assert.equal(en("kbItemCount", { folders: 0, documents: 0 }), "0 folders · 0 documents");
  assert.equal(tr("kbItemCount", { folders: 1, documents: 6 }), "1 klasör · 6 belge");
  assert.equal(tr("kbItemCount", { folders: 6, documents: 1 }), "6 klasör · 1 belge");
});

test("upload and re-queue counts pluralize", async () => {
  const { createTranslator } = await import("next-intl");
  const t = (locale: string, namespace: string) => createTranslator({ locale, messages: load(locale), namespace });
  const cases: [string, string, string, number, string][] = [
    ["en", "onboarding", "filesReady", 1, "1 file ready"],
    ["en", "onboarding", "filesReady", 3, "3 files ready"],
    ["en", "onboarding", "uploaded", 1, "Added 1 document."],
    ["en", "onboarding", "uploaded", 4, "Added 4 documents."],
    ["en", "admin", "uploaded", 1, "Uploaded 1 file."],
    ["en", "admin", "uploaded", 2, "Uploaded 2 files."],
    ["en", "admin", "retryFailedResult", 1, "1 document re-queued."],
    ["en", "admin", "retryFailedResult", 5, "5 documents re-queued."],
    ["tr", "onboarding", "filesReady", 3, "3 dosya hazır"],
    ["tr", "onboarding", "uploaded", 4, "4 döküman eklendi."],
    ["tr", "admin", "uploaded", 2, "2 dosya yüklendi."],
    ["tr", "admin", "retryFailedResult", 5, "5 belge yeniden kuyruğa alındı."],
  ];
  for (const [locale, ns, key, count, expected] of cases) {
    assert.equal(t(locale, ns)(key, { count }), expected, `${locale} ${ns}.${key} ${count}`);
  }
});

test('no "(s)" / "(es)" pseudo-plurals remain', () => {
  for (const l of ["en", "tr"]) {
    assert.doesNotMatch(readFileSync(path.join(import.meta.dirname, "..", "messages", `${l}.json`), "utf8"), /\((?:s|es)\)/);
  }
});
