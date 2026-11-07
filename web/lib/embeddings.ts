// SPDX-License-Identifier: Apache-2.0

// Admin "Embeddings & reranker" card: the control-plane payload
// (GET /api/v1/admin/embeddings) and the view model the card renders.

export type EmbeddingsProfile = {
  provider: string;
  model: string;
  dim: number;
  fingerprint: string;
  collection: string;
  sparse_model: string | null;
  reranker: { provider: string; model: string | null };
  // Hostnames document text is sent to; null = stays on this server.
  egress: { dense_host: string | null; rerank_host: string | null };
};

export type ReembedProgress = {
  target_fingerprint: string | null;
  total: number;
  completed: number;
  pending: number;
  processing: number;
  failed: number;
  stale: number;
  in_progress: boolean;
  last_started_at: string | null;
};

export type EmbeddingsStatus = {
  status: "ok" | "mismatch" | "unknown";
  policy: string;
  ingest_blocked: boolean;
  detail: string | null;
  profile: EmbeddingsProfile | null;
  stored_fingerprint: string | null;
  mismatch: boolean;
  checked_at: string | null;
  gateway_error: string | null;
  documents: { fingerprint: string | null; count: number }[];
  reembed: ReembedProgress;
};

export type ReembedResult = {
  fingerprint: string;
  collection: string;
  reembedded: number;
  skipped: number;
  workspaces: number;
};

export type ReembedErrorKind = "conflict" | "unavailable" | "invalid" | "forbidden" | "failed";

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);
const str = (v: unknown): string | null => (typeof v === "string" ? v : null);
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

const FINGERPRINT_RE = /^[0-9a-f]{8}$/;

/** The control plane's fingerprint pattern (ReembedIn). */
export const isFingerprint = (v: string) => FINGERPRINT_RE.test(v);

function parseProfile(v: unknown): EmbeddingsProfile | null {
  if (!isObj(v) || !isObj(v.reranker) || !isObj(v.egress)) return null;
  const provider = str(v.provider);
  const model = str(v.model);
  const dim = num(v.dim);
  const fingerprint = str(v.fingerprint);
  const collection = str(v.collection);
  const rerankerProvider = str(v.reranker.provider);
  if (!provider || !model || dim === null || !fingerprint || !collection || !rerankerProvider) return null;
  return {
    provider,
    model,
    dim,
    fingerprint,
    collection,
    sparse_model: str(v.sparse_model),
    reranker: { provider: rerankerProvider, model: str(v.reranker.model) },
    egress: { dense_host: str(v.egress.dense_host), rerank_host: str(v.egress.rerank_host) },
  };
}

function parseReembed(v: unknown): ReembedProgress | null {
  if (!isObj(v)) return null;
  const counts = ["total", "completed", "pending", "processing", "failed", "stale"] as const;
  const out: Partial<Record<(typeof counts)[number], number>> = {};
  for (const k of counts) {
    const n = num(v[k]);
    if (n === null) return null;
    out[k] = n;
  }
  return {
    target_fingerprint: str(v.target_fingerprint),
    ...(out as Record<(typeof counts)[number], number>),
    in_progress: v.in_progress === true,
    last_started_at: str(v.last_started_at),
  };
}

/** Validate the GET payload; null when it is not the documented shape. */
export function parseEmbeddingsStatus(data: unknown): EmbeddingsStatus | null {
  if (!isObj(data)) return null;
  const s = data.status;
  if (s !== "ok" && s !== "mismatch" && s !== "unknown") return null;
  if (!Array.isArray(data.documents)) return null;
  const reembed = parseReembed(data.reembed);
  if (!reembed) return null;
  return {
    status: s,
    policy: str(data.policy) ?? "",
    ingest_blocked: data.ingest_blocked === true,
    detail: str(data.detail),
    profile: parseProfile(data.profile),
    stored_fingerprint: str(data.stored_fingerprint),
    mismatch: data.mismatch === true,
    checked_at: str(data.checked_at),
    gateway_error: str(data.gateway_error),
    documents: data.documents.flatMap((d) => {
      if (!isObj(d)) return [];
      const count = num(d.count);
      const fp = d.fingerprint === null ? null : str(d.fingerprint);
      if (count === null || (fp === null && d.fingerprint !== null)) return [];
      return [{ fingerprint: fp, count }];
    }),
    reembed,
  };
}

export type EmbeddingsView = {
  mode: "local" | "cloud" | null;
  egress: { dense: string | null; rerank: string | null };
  banner: { kind: "mismatch" | "unknown"; detail: string | null } | null;
  gatewayError: string | null;
  documents: { fingerprint: string | null; count: number; current: boolean }[];
  stale: number;
  canReembed: boolean;
  // Which line the card shows next to the re-embed button.
  reembedHint: "needsProfile" | "stale" | "upToDate";
  polling: boolean;
  progress: {
    percent: number;
    total: number;
    completed: number;
    pending: number;
    processing: number;
    failed: number;
  } | null;
};

export function embeddingsView(s: EmbeddingsStatus): EmbeddingsView {
  const p = s.profile;
  const r = s.reembed;
  const canReembed = p !== null && !r.in_progress && (r.stale > 0 || s.mismatch);
  const banner =
    s.status === "mismatch" || s.mismatch
      ? ({ kind: "mismatch", detail: s.detail } as const)
      : s.status === "unknown"
        ? ({ kind: "unknown", detail: s.detail } as const)
        : null;
  return {
    mode: p ? (p.provider === "local" ? "local" : "cloud") : null,
    egress: { dense: p?.egress.dense_host ?? null, rerank: p?.egress.rerank_host ?? null },
    banner,
    gatewayError: s.gateway_error,
    documents: [...s.documents]
      .sort((a, b) => b.count - a.count)
      .map((d) => ({ ...d, current: p !== null && d.fingerprint === p.fingerprint })),
    stale: r.stale,
    canReembed,
    reembedHint: p === null ? "needsProfile" : canReembed ? "stale" : "upToDate",
    polling: r.in_progress,
    progress:
      r.total > 0
        ? {
            percent: Math.round((r.completed / r.total) * 100),
            total: r.total,
            completed: r.completed,
            pending: r.pending,
            processing: r.processing,
            failed: r.failed,
          }
        : null,
  };
}

/** POST /reembed failure → the message the card shows. */
export function reembedErrorKind(status: number): ReembedErrorKind {
  if (status === 409) return "conflict";
  if (status === 503) return "unavailable";
  if (status === 422) return "invalid";
  if (status === 401 || status === 403) return "forbidden";
  return "failed";
}
