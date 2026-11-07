// SPDX-License-Identifier: Apache-2.0

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  embeddingsView,
  isFingerprint,
  parseEmbeddingsStatus,
  reembedErrorKind,
  type EmbeddingsStatus,
} from "./embeddings.ts";

const localProfile = {
  provider: "local",
  model: "intfloat/multilingual-e5-large",
  dim: 1024,
  fingerprint: "a1b2c3d4",
  collection: "raggie_chunks_d1024",
  sparse_model: "Qdrant/bm25",
  reranker: { provider: "local", model: "gte-multilingual-reranker-base" },
  egress: { dense_host: null, rerank_host: null },
};

function status(over: Partial<EmbeddingsStatus> = {}): EmbeddingsStatus {
  return {
    status: "ok",
    policy: "block_ingest",
    ingest_blocked: false,
    detail: null,
    profile: localProfile,
    stored_fingerprint: "a1b2c3d4",
    mismatch: false,
    checked_at: "2026-11-04T10:00:00Z",
    gateway_error: null,
    documents: [{ fingerprint: "a1b2c3d4", count: 12 }],
    reembed: {
      target_fingerprint: "a1b2c3d4",
      total: 12,
      completed: 12,
      pending: 0,
      processing: 0,
      failed: 0,
      stale: 0,
      in_progress: false,
      last_started_at: null,
    },
    ...over,
  };
}

describe("parseEmbeddingsStatus", () => {
  test("accepts the control-plane payload", () => {
    assert.deepEqual(parseEmbeddingsStatus(JSON.parse(JSON.stringify(status()))), status());
  });

  test("rejects payloads without the required shape", () => {
    assert.equal(parseEmbeddingsStatus(null), null);
    assert.equal(parseEmbeddingsStatus({ status: "weird" }), null);
    assert.equal(parseEmbeddingsStatus({ ...status(), reembed: null }), null);
    assert.equal(parseEmbeddingsStatus({ ...status(), documents: "x" }), null);
  });

  test("drops a malformed profile and bad document rows instead of failing", () => {
    const parsed = parseEmbeddingsStatus({
      ...status(),
      profile: { provider: "local" },
      documents: [{ fingerprint: null, count: 3 }, { fingerprint: 5, count: "x" }],
    });
    assert.ok(parsed);
    assert.equal(parsed.profile, null);
    assert.deepEqual(parsed.documents, [{ fingerprint: null, count: 3 }]);
  });
});

describe("embeddingsView", () => {
  test("local profile: no egress, no banner, nothing to re-embed", () => {
    const v = embeddingsView(status());
    assert.equal(v.mode, "local");
    assert.deepEqual(v.egress, { dense: null, rerank: null });
    assert.equal(v.banner, null);
    assert.equal(v.canReembed, false);
    assert.equal(v.polling, false);
    assert.deepEqual(v.documents, [{ fingerprint: "a1b2c3d4", count: 12, current: true }]);
  });

  test("cloud provider with egress hosts", () => {
    const v = embeddingsView(
      status({
        profile: {
          ...localProfile,
          provider: "openai",
          egress: { dense_host: "api.openai.com", rerank_host: "api.cohere.com" },
        },
      }),
    );
    assert.equal(v.mode, "cloud");
    assert.deepEqual(v.egress, { dense: "api.openai.com", rerank: "api.cohere.com" });
  });

  test("an egress host is shown even when the provider says local", () => {
    const v = embeddingsView(
      status({ profile: { ...localProfile, egress: { dense_host: null, rerank_host: "rerank.example" } } }),
    );
    assert.equal(v.mode, "local");
    assert.deepEqual(v.egress, { dense: null, rerank: "rerank.example" });
  });

  test("mismatch: banner with the detail and re-embed available", () => {
    const v = embeddingsView(
      status({
        status: "mismatch",
        mismatch: true,
        ingest_blocked: true,
        detail: "different embedding profile",
        stored_fingerprint: "00000000",
        documents: [
          { fingerprint: "a1b2c3d4", count: 2 },
          { fingerprint: "00000000", count: 40 },
        ],
        reembed: { ...status().reembed, total: 2, completed: 2, stale: 40 },
      }),
    );
    assert.deepEqual(v.banner, { kind: "mismatch", detail: "different embedding profile" });
    assert.equal(v.canReembed, true);
    assert.equal(v.stale, 40);
    // Largest group first; the current fingerprint is flagged.
    assert.deepEqual(v.documents, [
      { fingerprint: "00000000", count: 40, current: false },
      { fingerprint: "a1b2c3d4", count: 2, current: true },
    ]);
  });

  test("unknown profile: banner, no mode and no re-embed", () => {
    const v = embeddingsView(
      status({ status: "unknown", profile: null, ingest_blocked: true, detail: "not known yet", gateway_error: "timeout" }),
    );
    assert.deepEqual(v.banner, { kind: "unknown", detail: "not known yet" });
    assert.equal(v.mode, null);
    assert.equal(v.canReembed, false);
    assert.equal(v.gatewayError, "timeout");
  });

  test("stale documents without a mismatch can still be re-embedded", () => {
    const v = embeddingsView(status({ reembed: { ...status().reembed, stale: 3 } }));
    assert.equal(v.banner, null);
    assert.equal(v.canReembed, true);
  });

  test("in progress: polling, progress percentage, no second run", () => {
    const v = embeddingsView(
      status({
        reembed: {
          ...status().reembed,
          total: 40,
          completed: 10,
          pending: 20,
          processing: 8,
          failed: 2,
          stale: 0,
          in_progress: true,
        },
      }),
    );
    assert.equal(v.polling, true);
    assert.equal(v.canReembed, false);
    assert.deepEqual(v.progress, { percent: 25, total: 40, completed: 10, pending: 20, processing: 8, failed: 2 });
  });

  test("progress is null when nothing targets the profile", () => {
    const v = embeddingsView(status({ reembed: { ...status().reembed, total: 0, completed: 0 } }));
    assert.equal(v.progress, null);
  });
});

describe("reembedHint", () => {
  test("up to date, stale, or waiting for the profile", () => {
    assert.equal(embeddingsView(status()).reembedHint, "upToDate");
    assert.equal(embeddingsView(status({ reembed: { ...status().reembed, stale: 3 } })).reembedHint, "stale");
    assert.equal(embeddingsView(status({ status: "unknown", profile: null })).reembedHint, "needsProfile");
  });
});

test("isFingerprint matches the control-plane pattern", () => {
  assert.equal(isFingerprint("a1b2c3d4"), true);
  assert.equal(isFingerprint("A1B2C3D4"), false);
  assert.equal(isFingerprint("a1b2c3d"), false);
  assert.equal(isFingerprint("a1b2c3d4e"), false);
});

test("reembedErrorKind maps the documented statuses", () => {
  assert.equal(reembedErrorKind(409), "conflict");
  assert.equal(reembedErrorKind(503), "unavailable");
  assert.equal(reembedErrorKind(422), "invalid");
  assert.equal(reembedErrorKind(403), "forbidden");
  assert.equal(reembedErrorKind(401), "forbidden");
  assert.equal(reembedErrorKind(500), "failed");
  assert.equal(reembedErrorKind(0), "failed");
});
