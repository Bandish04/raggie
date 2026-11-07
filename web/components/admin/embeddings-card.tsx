// SPDX-License-Identifier: Apache-2.0

"use client";

import { useFormatter, useTranslations } from "next-intl";
import { useCallback, useEffect, useState, useTransition } from "react";

import { reembedAction } from "@/app/admin/ai/actions";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Icon } from "@/components/ui/icon";
import { Modal } from "@/components/ui/modal";
import {
  embeddingsView,
  parseEmbeddingsStatus,
  type EmbeddingsStatus,
  type ReembedErrorKind,
  type ReembedResult,
} from "@/lib/embeddings";

const POLL_MS = 3000;

const REEMBED_ERROR_KEY = {
  conflict: "embReembedErrorConflict",
  unavailable: "embReembedErrorUnavailable",
  invalid: "embReembedErrorInvalid",
  forbidden: "embReembedErrorForbidden",
  failed: "embReembedErrorFailed",
} as const satisfies Record<ReembedErrorKind, string>;

// Platform-admin card: what the embeddings gateway runs, where document text
// goes, whether the indexed documents match it, and the re-embed switch.
export default function EmbeddingsCard({ initial }: { initial: EmbeddingsStatus | null }) {
  const t = useTranslations("admin");
  const tc = useTranslations("common");
  const format = useFormatter();
  const [status, setStatus] = useState(initial);
  const [loadFailed, setLoadFailed] = useState(initial === null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [error, setError] = useState<ReembedErrorKind | null>(null);
  const [started, setStarted] = useState<ReembedResult | null>(null);
  const [pending, start] = useTransition();

  const refresh = useCallback(async () => {
    try {
      const res = await fetch("/api/admin/embeddings", { cache: "no-store" });
      const parsed = res.ok ? parseEmbeddingsStatus(await res.json()) : null;
      if (parsed) setStatus(parsed);
      setLoadFailed(parsed === null);
    } catch {
      setLoadFailed(true);
    }
  }, []);

  const view = status ? embeddingsView(status) : null;
  const polling = view?.polling ?? false;

  // Poll while a re-embed is running; stop as soon as it finishes.
  useEffect(() => {
    if (!polling) return;
    const id = setInterval(() => void refresh(), POLL_MS);
    return () => clearInterval(id);
  }, [polling, refresh]);

  function reembed() {
    const fingerprint = status?.profile?.fingerprint;
    if (!fingerprint) return;
    setError(null);
    start(async () => {
      const res = await reembedAction(fingerprint);
      setConfirmOpen(false);
      if (res.ok) setStarted(res.result);
      else setError(res.error);
      // Either way show the current state: a 409 usually means the gateway changed.
      await refresh();
    });
  }

  if (!status || !view) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{t("embTitle")}</CardTitle>
        </CardHeader>
        <CardBody className="space-y-3">
          <p className="text-sm text-danger" role="alert">
            {t("embLoadFailed")}
          </p>
          <Button variant="ghost" size="sm" onClick={() => void refresh()}>
            {t("embRetry")}
          </Button>
        </CardBody>
      </Card>
    );
  }

  const p = status.profile;
  const egressHosts = [view.egress.dense, view.egress.rerank].filter((h): h is string => Boolean(h));
  const costHost = view.egress.dense ?? p?.provider ?? "";

  return (
    <Card>
      <CardHeader>
        <div className="min-w-0">
          <CardTitle>{t("embTitle")}</CardTitle>
          <CardDescription>{t("embSubtitle")}</CardDescription>
        </div>
        {view.mode ? (
          <Badge tone={view.mode === "cloud" ? "warning" : "success"} dot>
            {view.mode === "cloud" ? t("embModeCloud") : t("embModeLocal")}
          </Badge>
        ) : null}
      </CardHeader>

      <CardBody className="space-y-5">
        {egressHosts.length > 0 ? (
          <div className="flex items-start gap-3 rounded-2xl border border-warning/40 bg-warning/10 p-4" role="note">
            <Icon name="public" size={22} className="mt-0.5 shrink-0 text-warning" />
            <div className="min-w-0 text-sm">
              <p className="font-semibold uppercase tracking-wide text-warning">{t("embEgressTitle")}</p>
              {view.egress.dense ? (
                <p className="mt-1 text-ink">{t("embEgressDense", { host: view.egress.dense })}</p>
              ) : null}
              {view.egress.rerank ? (
                <p className="mt-1 text-ink">{t("embEgressRerank", { host: view.egress.rerank })}</p>
              ) : null}
            </div>
          </div>
        ) : p ? (
          <p className="flex items-center gap-2 text-sm text-ink-muted">
            <Icon name="shield" size={18} className="text-success" />
            {t("embNoEgress")}
          </p>
        ) : null}

        {view.banner ? (
          <div
            className={`rounded-2xl p-4 text-sm ${
              view.banner.kind === "mismatch" ? "bg-danger/10 text-danger" : "bg-warning/10 text-warning"
            }`}
            role="alert"
          >
            <p className="font-semibold">
              {view.banner.kind === "mismatch" ? t("embBannerMismatch") : t("embBannerUnknown")}
            </p>
            {view.banner.detail ? <p className="mt-1 text-ink">{view.banner.detail}</p> : null}
          </div>
        ) : view.gatewayError ? (
          <p className="rounded-2xl bg-warning/10 px-4 py-3 text-sm text-warning">
            {t("embGatewayError", { error: view.gatewayError })}
          </p>
        ) : null}

        {p ? (
          <dl className="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
            <Field label={t("embProvider")} value={p.provider} />
            <Field label={t("embModel")} value={p.model} mono />
            <Field label={t("embDim")} value={format.number(p.dim)} />
            <Field label={t("embCollection")} value={p.collection} mono />
            <Field label={t("embFingerprint")} value={p.fingerprint} mono />
            <Field label={t("embSparse")} value={p.sparse_model ?? "—"} mono />
            <Field
              label={t("embReranker")}
              value={p.reranker.model ? `${p.reranker.provider} · ${p.reranker.model}` : p.reranker.provider}
              mono
            />
            <Field
              label={t("embCheckedAt")}
              value={
                status.checked_at
                  ? format.dateTime(new Date(status.checked_at), { dateStyle: "medium", timeStyle: "short" })
                  : "—"
              }
            />
          </dl>
        ) : null}

        <div>
          <h4 className="text-sm font-semibold text-ink">{t("embDocuments")}</h4>
          {view.documents.length === 0 ? (
            <p className="mt-2 text-sm text-ink-muted">{t("embNoDocuments")}</p>
          ) : (
            <ul className="mt-2 divide-y divide-border overflow-hidden rounded-2xl border border-border">
              {view.documents.map((d) => (
                <li key={d.fingerprint ?? "none"} className="flex items-center justify-between gap-3 px-4 py-2.5 text-sm">
                  <span className="flex min-w-0 items-center gap-2">
                    <span className={d.fingerprint ? "truncate font-mono" : "truncate text-ink-muted"}>
                      {d.fingerprint ?? t("embNoFingerprint")}
                    </span>
                    {d.current ? <Badge tone="brand">{t("embCurrent")}</Badge> : null}
                  </span>
                  <span className="shrink-0 tabular-nums text-ink-muted">
                    {t("embDocCount", { count: d.count })}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="space-y-3 border-t border-border pt-5">
          {view.polling && view.progress ? (
            <div className="space-y-2" aria-live="polite">
              <div className="flex items-center justify-between text-sm">
                <span className="font-medium text-ink">{t("embReembedRunning")}</span>
                <span className="tabular-nums text-ink-muted">
                  {t("embProgress", { completed: view.progress.completed, total: view.progress.total })}
                </span>
              </div>
              <div className="h-2 w-full overflow-hidden rounded-full bg-surface-2">
                <div
                  className="h-full rounded-full bg-brand transition-[width] duration-300 ease-out"
                  style={{ width: `${view.progress.percent}%` }}
                  role="progressbar"
                  aria-label={t("embReembedRunning")}
                  aria-valuenow={view.progress.percent}
                  aria-valuemin={0}
                  aria-valuemax={100}
                />
              </div>
              <p className="text-xs text-ink-muted">
                {t("embProgressDetail", {
                  pending: view.progress.pending,
                  processing: view.progress.processing,
                  failed: view.progress.failed,
                })}
              </p>
            </div>
          ) : (
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-sm text-ink-muted">
                {view.reembedHint === "stale"
                  ? t("embStale", { count: view.stale })
                  : view.reembedHint === "needsProfile"
                    ? t("embNeedsProfile")
                    : t("embUpToDate")}
              </p>
              <Button onClick={() => setConfirmOpen(true)} disabled={!view.canReembed || pending}>
                <Icon name="sync" size={18} />
                {t("embReembed")}
              </Button>
            </div>
          )}

          {status.reembed.last_started_at ? (
            <p className="text-xs text-ink-muted">
              {t("embLastStarted", {
                at: format.dateTime(new Date(status.reembed.last_started_at), {
                  dateStyle: "medium",
                  timeStyle: "short",
                }),
              })}
            </p>
          ) : null}
          {started ? (
            <p className="text-sm text-success" role="status">
              {t("embReembedStarted", { count: started.reembedded, workspaces: started.workspaces })}
              {started.skipped > 0 ? ` ${t("embReembedSkipped", { count: started.skipped })}` : ""}
            </p>
          ) : null}
          {error ? (
            <p className="text-sm text-danger" role="alert">
              {t(REEMBED_ERROR_KEY[error])}
            </p>
          ) : null}
          {loadFailed ? <p className="text-xs text-danger">{t("embLoadFailed")}</p> : null}
        </div>
      </CardBody>

      <Modal
        open={confirmOpen}
        onClose={() => !pending && setConfirmOpen(false)}
        title={t("embConfirmTitle", { count: view.stale })}
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirmOpen(false)} disabled={pending}>
              {tc("cancel")}
            </Button>
            <Button onClick={reembed} disabled={pending}>
              {pending ? t("embReembedStarting") : t("embConfirmCta")}
            </Button>
          </>
        }
      >
        <div className="space-y-3 text-sm text-ink">
          <p>{t("embConfirmBody", { model: p?.model ?? "", collection: p?.collection ?? "" })}</p>
          <p className="text-ink-muted">{t("embConfirmKeepOld")}</p>
          {view.mode === "cloud" ? (
            <p className="rounded-2xl bg-warning/10 p-3 text-warning" role="note">
              {t("embConfirmCloudCost", { count: view.stale, host: costHost })}
            </p>
          ) : null}
        </div>
      </Modal>
    </Card>
  );
}

function Field({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs uppercase tracking-wider text-ink-muted">{label}</dt>
      <dd className={`mt-0.5 break-all text-ink ${mono ? "font-mono text-[13px]" : ""}`}>{value}</dd>
    </div>
  );
}
