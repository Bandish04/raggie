// SPDX-License-Identifier: Apache-2.0

import assert from "node:assert/strict";
import { test } from "node:test";

import { classifyUploadFailure, uploadFailureMessage, uploadRefusalMessage } from "./upload-errors.ts";

test("409 mentioning the embedding profile is a fingerprint mismatch", () => {
  assert.deepEqual(
    classifyUploadFailure(409, "The embeddings gateway now uses a different embedding profile (...)", null),
    { code: "embedding_mismatch" },
  );
});

test("503 is an unknown embedding profile and carries Retry-After", () => {
  assert.deepEqual(classifyUploadFailure(503, "The embedding profile is not known yet", "30"), {
    code: "embedding_unavailable",
    retryAfterSeconds: 30,
  });
  assert.deepEqual(classifyUploadFailure(503, "", null), {
    code: "embedding_unavailable",
    retryAfterSeconds: null,
  });
});

test("other failures are not classified", () => {
  assert.deepEqual(classifyUploadFailure(409, "folder already exists", null), { code: null });
  assert.deepEqual(classifyUploadFailure(413, "too large", null), { code: null });
  assert.deepEqual(classifyUploadFailure(500, "boom", "5"), { code: null });
});

test("uploadFailureMessage picks the translated message for embedding refusals", () => {
  assert.deepEqual(uploadFailureMessage({ code: "embedding_mismatch" }), { key: "uploadEmbeddingMismatch" });
  assert.deepEqual(uploadFailureMessage({ code: "embedding_unavailable", retryAfterSeconds: 30 }), {
    key: "uploadEmbeddingUnavailable",
    values: { seconds: 30 },
  });
  assert.deepEqual(uploadFailureMessage({ code: "embedding_unavailable", retryAfterSeconds: null }), {
    key: "uploadEmbeddingUnavailableSoon",
  });
  assert.equal(uploadFailureMessage({}), null);
});

test("uploadRefusalMessage classifies a raw response in one step (server-side uploads)", () => {
  assert.deepEqual(uploadRefusalMessage(409, '{"detail":"different embedding profile"}', null), {
    key: "uploadEmbeddingMismatch",
  });
  assert.deepEqual(uploadRefusalMessage(503, '{"detail":"not known yet"}', "30"), {
    key: "uploadEmbeddingUnavailable",
    values: { seconds: 30 },
  });
  assert.equal(uploadRefusalMessage(409, '{"detail":"folder already exists"}', null), null);
  assert.equal(uploadRefusalMessage(500, "not json", null), null);
  assert.equal(uploadRefusalMessage(200, "", null), null);
});
