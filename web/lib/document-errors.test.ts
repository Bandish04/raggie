// SPDX-License-Identifier: Apache-2.0

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { documentFailure, DOCUMENT_FAILURE_KEYS } from "./document-errors.ts";

const doc = (error_code: string | null, error_params: Record<string, unknown> | null = null, error_message: string | null = "English reason.") => ({
  error_code,
  error_params,
  error_message,
});

describe("documentFailure: known codes", () => {
  test("parse_limit with a numeric limit", () => {
    assert.deepEqual(documentFailure(doc("parse_limit", { kind: "pdf_pages", limit: 1000 })), {
      key: "docErrorParseLimit",
      values: { kind: "pdf_pages", limit: 1000 },
      detail: null,
    });
  });
  test("parse_limit without a limit, unknown kinds and complexity", () => {
    assert.deepEqual(documentFailure(doc("parse_limit", { kind: "xlsx_rows" })), {
      key: "docErrorParseLimitNoValue",
      values: { kind: "xlsx_rows" },
      detail: null,
    });
    // An unknown kind is passed through: the ICU select falls back to `other`.
    assert.deepEqual(documentFailure(doc("parse_limit", { kind: "brand_new", limit: 3 })).values, {
      kind: "brand_new",
      limit: 3,
    });
    assert.deepEqual(documentFailure(doc("parse_limit", { kind: "complexity" })), {
      key: "docErrorParseComplexity",
      values: {},
      detail: null,
    });
    assert.deepEqual(documentFailure(doc("parse_limit", null)).key, "docErrorParseLimitNoValue");
    assert.deepEqual(documentFailure(doc("parse_limit", null)).values, { kind: "other" });
  });
  test("parameterized codes fall back to their no-value message when a param is missing or malformed", () => {
    assert.deepEqual(documentFailure(doc("unsupported_format", { extension: ".zip" })), {
      key: "docErrorUnsupportedFormat",
      values: { extension: ".zip" },
      detail: null,
    });
    assert.equal(documentFailure(doc("unsupported_format", { extension: "<script>" })).key, "docErrorUnsupportedFormatNoValue");
    assert.deepEqual(documentFailure(doc("parse_timeout", { seconds: 120 })).values, { seconds: 120 });
    assert.equal(documentFailure(doc("parse_timeout", { seconds: "120" })).key, "docErrorParseTimeoutNoValue");
    assert.deepEqual(documentFailure(doc("parser_crashed", { exit_code: -9 })).values, { exitCode: -9 });
    assert.equal(documentFailure(doc("parser_crashed", { exit_code: null })).key, "docErrorParserCrashedNoValue");
    assert.deepEqual(documentFailure(doc("fingerprint_mismatch", { expected: "2872ae6a", actual: "5e1f00d2" })).values, {
      expected: "2872ae6a",
      actual: "5e1f00d2",
    });
    assert.equal(
      documentFailure(doc("fingerprint_mismatch", { expected: "x", actual: "5e1f00d2" })).key,
      "docErrorFingerprintMismatchNoValue",
    );
    assert.deepEqual(documentFailure(doc("embeddings_http", { status: 503 })).values, { status: 503 });
    assert.equal(documentFailure(doc("embeddings_http", {})).key, "docErrorEmbeddingsHttpNoValue");
  });
  test("parameterless codes", () => {
    for (const [code, key] of [
      ["parse_invalid", "docErrorParseInvalid"],
      ["embeddings_unreachable", "docErrorEmbeddingsUnreachable"],
      ["vector_store", "docErrorVectorStore"],
      ["object_read", "docErrorObjectRead"],
      ["unexpected", "docErrorUnexpected"],
    ] as const) {
      assert.deepEqual(documentFailure(doc(code)), { key, values: {}, detail: null });
    }
  });
});

describe("documentFailure: unknown or missing codes", () => {
  test("show the generic message with the English error_message as detail", () => {
    assert.deepEqual(documentFailure(doc("from_the_future", { x: 1 }, "Something new broke.")), {
      key: "docErrorUnknown",
      values: {},
      detail: "Something new broke.",
    });
    assert.deepEqual(documentFailure(doc(null, null, "Old failure.")), {
      key: "docErrorUnknown",
      values: {},
      detail: "Old failure.",
    });
    assert.deepEqual(documentFailure({}), { key: "docErrorUnknown", values: {}, detail: null });
  });
});

test("every key the mapper can return is listed for the i18n catalogs", () => {
  assert.ok(DOCUMENT_FAILURE_KEYS.includes("docErrorUnknown"));
  assert.equal(new Set(DOCUMENT_FAILURE_KEYS).size, DOCUMENT_FAILURE_KEYS.length);
});

test("every failure message exists in en and tr and formats with the mapper's values", async () => {
  const { createTranslator } = await import("next-intl");
  const { readFileSync } = await import("node:fs");
  const samples = [
    doc("parse_limit", { kind: "pdf_pages", limit: 1000 }),
    doc("parse_limit", { kind: "brand_new", limit: 5 }),
    doc("parse_limit", { kind: "xlsx_rows" }),
    doc("parse_limit", { kind: "complexity" }),
    doc("parse_invalid"),
    doc("unsupported_format", { extension: ".zip" }),
    doc("unsupported_format", {}),
    doc("parse_timeout", { seconds: 120 }),
    doc("parse_timeout", {}),
    doc("parser_crashed", { exit_code: -9 }),
    doc("parser_crashed", {}),
    doc("fingerprint_mismatch", { expected: "2872ae6a", actual: "5e1f00d2" }),
    doc("fingerprint_mismatch", {}),
    doc("embeddings_http", { status: 503 }),
    doc("embeddings_http", {}),
    doc("embeddings_unreachable"),
    doc("vector_store"),
    doc("object_read"),
    doc("unexpected"),
    doc("nope"),
  ];
  const covered = new Set(samples.map((s) => documentFailure(s).key));
  assert.deepEqual([...covered].sort(), [...DOCUMENT_FAILURE_KEYS].sort());
  for (const locale of ["en", "tr"]) {
    const messages = JSON.parse(readFileSync(new URL(`../messages/${locale}.json`, import.meta.url), "utf8"));
    const t = createTranslator({ locale, messages, namespace: "admin" });
    for (const sample of samples) {
      const { key, values } = documentFailure(sample);
      const text = t(key, values);
      assert.ok(text && !text.includes("{") && !text.startsWith("admin."), `${locale} ${key}: ${text}`);
    }
  }
  const en = JSON.parse(readFileSync(new URL("../messages/en.json", import.meta.url), "utf8"));
  const t = createTranslator({ locale: "en", messages: en, namespace: "admin" });
  assert.equal(
    t("docErrorParseLimit", { kind: "pdf_pages", limit: 1000 }),
    "A processing limit was exceeded: PDF pages (limit 1,000).",
  );
  assert.equal(t("docErrorParseLimit", { kind: "brand_new", limit: 5 }), "A processing limit was exceeded: other limit (limit 5).");
});
