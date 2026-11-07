// SPDX-License-Identifier: Apache-2.0

"use client";

import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";

import type { QdrantScatter } from "@/lib/api";

const PALETTE = [
  "#0a5bff", "#15a34a", "#ef4444", "#a855f7", "#f59e0b",
  "#06b6d4", "#ec4899", "#84cc16", "#6366f1", "#f97316",
];
const NO_DOC = "—";

export default function VectorMap({
  scatter,
  workspaceNames,
}: {
  scatter: QdrantScatter | null;
  workspaceNames: Record<string, string>;
}) {
  const t = useTranslations("admin");
  const [hover, setHover] = useState<number | null>(null);

  const view = useMemo(() => {
    const pts = scatter?.points ?? [];
    if (pts.length === 0) return null;
    const edges = scatter?.edges ?? [];

    const xs = pts.map((p) => p.x);
    const ys = pts.map((p) => p.y);
    const minX = Math.min(...xs), maxX = Math.max(...xs);
    const minY = Math.min(...ys), maxY = Math.max(...ys);
    const W = 760, H = 460, pad = 28;
    const sx = (x: number) =>
      maxX === minX ? W / 2 : pad + ((x - minX) / (maxX - minX)) * (W - 2 * pad);
    const sy = (y: number) =>
      maxY === minY ? H / 2 : pad + ((y - minY) / (maxY - minY)) * (H - 2 * pad);

    // Color by document. Each point's document key drives both color and the
    // hover cluster; workspace stays available on the hover readout.
    const docKey = (i: number) => pts[i].document_id ?? NO_DOC;
    const docIds = Array.from(new Set(pts.map((_, i) => docKey(i))));
    const colorOf = (i: number) => PALETTE[docIds.indexOf(docKey(i)) % PALETTE.length];

    // A short, friendly label per document — filename when present.
    const docLabel = (id: string) => {
      const p = pts.find((q) => (q.document_id ?? NO_DOC) === id);
      if (id === NO_DOC) return t("qdrantNoDocument");
      return p?.filename ?? id.slice(0, 8);
    };

    return { pts, edges, W, H, sx, sy, docIds, docKey, colorOf, docLabel };
  }, [scatter, t]);

  if (!view) {
    return (
      <div className="rounded-2xl border border-border bg-surface p-10 text-center text-sm text-ink-muted">
        {t("qdrantEmpty")}
      </div>
    );
  }

  const { pts, edges, W, H, sx, sy, docIds, docKey, colorOf, docLabel } = view;

  // The document being highlighted (the hovered node's document), if any.
  const activeDoc = hover !== null ? docKey(hover) : null;
  const isActive = (i: number) => activeDoc !== null && docKey(i) === activeDoc;
  const docCount = docIds.filter((d) => d !== NO_DOC).length;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3 text-sm text-ink-muted">
        <span className="rounded-full bg-surface-2 px-3 py-1">
          {t("qdrantCollection")}: <code className="text-ink">{scatter?.collection}</code>
        </span>
        <span className="rounded-full bg-surface-2 px-3 py-1">
          {t("qdrantPoints")}: <span className="text-ink">{scatter?.total}</span>
        </span>
        <span className="rounded-full bg-surface-2 px-3 py-1">
          {t("qdrantDocuments")}: <span className="text-ink">{docCount}</span>
        </span>
      </div>

      <div className="flex flex-wrap gap-x-3 gap-y-1.5">
        {docIds.slice(0, 12).map((id) => {
          const idx = pts.findIndex((_, i) => docKey(i) === id);
          return (
            <span key={id} className="inline-flex items-center gap-1.5 text-xs text-ink-muted">
              <span className="h-2.5 w-2.5 rounded-full" style={{ background: colorOf(idx) }} />
              {docLabel(id)}
            </span>
          );
        })}
        {docIds.length > 12 && (
          <span className="text-xs text-ink-muted/70">{t("qdrantMoreDocuments", { count: docIds.length - 12 })}</span>
        )}
      </div>

      <div className="overflow-x-auto rounded-2xl border border-border bg-surface p-3">
        <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label={t("qdrantTitle")}>
          {/* Edges first, beneath the nodes: faint links between sibling chunks. */}
          <g>
            {edges.map(([a, b], i) => {
              const on = isActive(a) || isActive(b);
              return (
                <line
                  key={i}
                  x1={sx(pts[a].x)}
                  y1={sy(pts[a].y)}
                  x2={sx(pts[b].x)}
                  y2={sy(pts[b].y)}
                  stroke={colorOf(a)}
                  strokeWidth={on ? 1.4 : 0.8}
                  strokeOpacity={activeDoc === null ? 0.18 : on ? 0.55 : 0.05}
                  style={{ transition: "stroke-opacity 0.1s, stroke-width 0.1s" }}
                />
              );
            })}
          </g>
          {pts.map((p, i) => {
            const on = isActive(i);
            const dim = activeDoc !== null && !on;
            return (
              <circle
                key={i}
                cx={sx(p.x)}
                cy={sy(p.y)}
                r={hover === i ? 6 : on ? 4.5 : 3.5}
                fill={colorOf(i)}
                fillOpacity={dim ? 0.25 : 0.85}
                onMouseEnter={() => setHover(i)}
                onMouseLeave={() => setHover(null)}
                style={{ cursor: "pointer", transition: "r 0.1s, fill-opacity 0.1s" }}
              />
            );
          })}
        </svg>
      </div>

      {hover !== null && pts[hover] && (
        <p className="text-sm text-ink-muted">
          <span className="material-symbols-outlined align-middle text-base text-brand">description</span>{" "}
          {pts[hover].filename ?? "—"}
          {pts[hover].workspace_id && (
            <span className="ml-2 text-ink-muted/70">
              · {workspaceNames[pts[hover].workspace_id] ?? pts[hover].workspace_id.slice(0, 8)}
            </span>
          )}
        </p>
      )}
      <p className="text-xs text-ink-muted/70">{t("qdrantHint")}</p>
    </div>
  );
}
