// SPDX-License-Identifier: Apache-2.0

// Upload refusals caused by the embedding profile (control plane, documents.py):
// 409 while the gateway's profile no longer matches the indexed documents, 503
// (+ Retry-After) while the profile is not known yet. Both are shown as
// friendly, translated messages instead of the raw detail.

import { retryAfterSeconds } from "./chat-retry.ts";

export type UploadFailureCode = "embedding_mismatch" | "embedding_unavailable";

export type UploadFailure =
  | { code: "embedding_mismatch" }
  | { code: "embedding_unavailable"; retryAfterSeconds: number | null }
  | { code: null };

export function classifyUploadFailure(
  status: number,
  detail: string,
  retryAfter: string | null,
): UploadFailure {
  // Folder/name conflicts are 409 too; only the embedding guard mentions it.
  if (status === 409 && /embedding/i.test(detail)) return { code: "embedding_mismatch" };
  if (status === 503) return { code: "embedding_unavailable", retryAfterSeconds: retryAfterSeconds(retryAfter) };
  return { code: null };
}

export type UploadFailureMessage =
  | { key: "uploadEmbeddingMismatch" | "uploadEmbeddingUnavailableSoon" }
  | { key: "uploadEmbeddingUnavailable"; values: { seconds: number } };

/** The admin.* message for a classified upload failure, or null to show the raw error. */
export function uploadFailureMessage(f: {
  code?: UploadFailureCode;
  retryAfterSeconds?: number | null;
}): UploadFailureMessage | null {
  if (f.code === "embedding_mismatch") return { key: "uploadEmbeddingMismatch" };
  if (f.code === "embedding_unavailable") {
    return f.retryAfterSeconds
      ? { key: "uploadEmbeddingUnavailable", values: { seconds: f.retryAfterSeconds } }
      : { key: "uploadEmbeddingUnavailableSoon" };
  }
  return null;
}

/** One step from a raw control-plane response (status, body text, Retry-After)
 *  to the message, for uploads done server-side (onboarding). */
export function uploadRefusalMessage(
  status: number,
  body: string,
  retryAfter: string | null,
): UploadFailureMessage | null {
  let detail = body;
  try {
    const parsed = JSON.parse(body) as { detail?: unknown };
    if (typeof parsed.detail === "string") detail = parsed.detail;
  } catch {
    // Not JSON: classify the raw text.
  }
  const failure = classifyUploadFailure(status, detail, retryAfter);
  return failure.code === null ? null : uploadFailureMessage(failure);
}
