// SPDX-License-Identifier: Apache-2.0

// Document ingestion failure → the admin.* message key and its values, from the
// stable `error_code` + `error_params` (contracts/document_errors.md). Params
// come from the database, so each one is type-checked before it reaches a
// message; a missing or malformed param picks the code's "no value" message.
// Unknown or missing codes show a generic message with the English
// `error_message` as a secondary detail.

export const DOCUMENT_FAILURE_KEYS = [
  "docErrorParseLimit",
  "docErrorParseLimitNoValue",
  "docErrorParseComplexity",
  "docErrorParseInvalid",
  "docErrorUnsupportedFormat",
  "docErrorUnsupportedFormatNoValue",
  "docErrorParseTimeout",
  "docErrorParseTimeoutNoValue",
  "docErrorParserCrashed",
  "docErrorParserCrashedNoValue",
  "docErrorFingerprintMismatch",
  "docErrorFingerprintMismatchNoValue",
  "docErrorEmbeddingsHttp",
  "docErrorEmbeddingsHttpNoValue",
  "docErrorEmbeddingsUnreachable",
  "docErrorVectorStore",
  "docErrorObjectRead",
  "docErrorUnexpected",
  "docErrorUnknown",
] as const;

export type DocumentFailureKey = (typeof DOCUMENT_FAILURE_KEYS)[number];

export type DocumentFailure = {
  key: DocumentFailureKey;
  values: Record<string, string | number>;
  // The English error_message, only for unknown/missing codes.
  detail: string | null;
};

type FailedDocument = {
  error_code?: string | null;
  error_params?: Record<string, unknown> | null;
  error_message?: string | null;
};

const int = (v: unknown): number | null => (typeof v === "number" && Number.isInteger(v) ? v : null);
const KIND_RE = /^[a-z_]{1,40}$/;
const EXTENSION_RE = /^\.[a-z0-9]{1,10}$/i;
const FINGERPRINT_RE = /^[0-9a-f]{8}$/;

const known = (key: DocumentFailureKey, values: Record<string, string | number> = {}): DocumentFailure => ({
  key,
  values,
  detail: null,
});

export function documentFailure(doc: FailedDocument): DocumentFailure {
  const p = doc.error_params ?? {};
  switch (doc.error_code) {
    case "parse_limit": {
      const kind = typeof p.kind === "string" && KIND_RE.test(p.kind) ? p.kind : "other";
      if (kind === "complexity") return known("docErrorParseComplexity");
      const limit = int(p.limit);
      return limit === null
        ? known("docErrorParseLimitNoValue", { kind })
        : known("docErrorParseLimit", { kind, limit });
    }
    case "parse_invalid":
      return known("docErrorParseInvalid");
    case "unsupported_format":
      return typeof p.extension === "string" && EXTENSION_RE.test(p.extension)
        ? known("docErrorUnsupportedFormat", { extension: p.extension })
        : known("docErrorUnsupportedFormatNoValue");
    case "parse_timeout": {
      const seconds = int(p.seconds);
      return seconds === null ? known("docErrorParseTimeoutNoValue") : known("docErrorParseTimeout", { seconds });
    }
    case "parser_crashed": {
      const exitCode = int(p.exit_code);
      return exitCode === null
        ? known("docErrorParserCrashedNoValue")
        : known("docErrorParserCrashed", { exitCode });
    }
    case "fingerprint_mismatch":
      return typeof p.expected === "string" &&
        typeof p.actual === "string" &&
        FINGERPRINT_RE.test(p.expected) &&
        FINGERPRINT_RE.test(p.actual)
        ? known("docErrorFingerprintMismatch", { expected: p.expected, actual: p.actual })
        : known("docErrorFingerprintMismatchNoValue");
    case "embeddings_http": {
      const status = int(p.status);
      return status === null ? known("docErrorEmbeddingsHttpNoValue") : known("docErrorEmbeddingsHttp", { status });
    }
    case "embeddings_unreachable":
      return known("docErrorEmbeddingsUnreachable");
    case "vector_store":
      return known("docErrorVectorStore");
    case "object_read":
      return known("docErrorObjectRead");
    case "unexpected":
      return known("docErrorUnexpected");
    default:
      return { key: "docErrorUnknown", values: {}, detail: doc.error_message?.trim() || null };
  }
}
