// SPDX-License-Identifier: Apache-2.0

"use client";

import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";

import { EmptyState } from "@/components/ui/empty-state";
import { Icon } from "@/components/ui/icon";
import type { OrgChartNode } from "@/lib/api";

// A node in the rendered reporting tree. `reports` are the people who report to
// this node. The synthetic root buckets everyone whose manager is unset or
// points outside the org.
type TreeNode = {
  node: OrgChartNode | null; // null only for the synthetic root
  reports: TreeNode[];
};

/**
 * Build a manager-based reporting tree from flat nodes.
 *
 * Cycle handling: we walk the children of each node depth-first while carrying a
 * `path` set of ancestor ids. Before descending into a child we check whether the
 * child id is already on the current path; if so we STOP (do not recurse), which
 * breaks A→B→A style cycles and self-references without ever infinite-looping.
 * A separate `placed` set guarantees every user is attached exactly once, so a
 * member caught in a cycle still surfaces (under whichever manager reaches it
 * first), never silently disappearing.
 */
function buildTree(nodes: OrgChartNode[]): TreeNode {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const childrenOf = new Map<string, OrgChartNode[]>();
  const roots: OrgChartNode[] = [];

  for (const n of nodes) {
    const mgr = n.manager_user_id;
    // Root = no manager, self-managed, or a manager that isn't in the set.
    if (!mgr || mgr === n.id || !byId.has(mgr)) {
      roots.push(n);
    } else {
      const arr = childrenOf.get(mgr) ?? [];
      arr.push(n);
      childrenOf.set(mgr, arr);
    }
  }

  const placed = new Set<string>();
  const build = (n: OrgChartNode, path: Set<string>): TreeNode => {
    placed.add(n.id);
    const nextPath = new Set(path);
    nextPath.add(n.id);
    const reports: TreeNode[] = [];
    for (const child of childrenOf.get(n.id) ?? []) {
      // Break cycles: skip a child already on the current ancestor path, and
      // never place the same person twice.
      if (nextPath.has(child.id) || placed.has(child.id)) continue;
      reports.push(build(child, nextPath));
    }
    return { node: n, reports: sortTree(reports) };
  };

  const rootChildren = roots.map((r) => build(r, new Set<string>()));

  // Safety net: anyone not yet placed (only possible inside a pure cycle whose
  // members all had in-set managers) is attached to the synthetic root so the
  // chart stays complete.
  for (const n of nodes) {
    if (!placed.has(n.id)) rootChildren.push(build(n, new Set<string>()));
  }

  return { node: null, reports: sortTree(rootChildren) };
}

function sortTree(nodes: TreeNode[]): TreeNode[] {
  return [...nodes].sort((a, b) => {
    const an = a.node ? a.node.name || a.node.email : "";
    const bn = b.node ? b.node.name || b.node.email : "";
    return an.localeCompare(bn);
  });
}

function Row({ tn, depth }: { tn: TreeNode; depth: number }) {
  const t = useTranslations("admin");
  const [open, setOpen] = useState(true);
  const hasReports = tn.reports.length > 0;
  const n = tn.node;

  const label = n ? n.name || n.email : t("orgChartTopLevel");
  const subtitle = n?.job_title || n?.department || null;

  return (
    <li>
      <div
        className="flex items-center gap-2 rounded-xl py-2 pr-2 transition hover:bg-surface-2"
        style={{ paddingLeft: `${0.5 + depth * 1.25}rem` }}
      >
        {hasReports ? (
          <button
            type="button"
            onClick={() => setOpen((o) => !o)}
            aria-expanded={open}
            aria-label={open ? t("orgChartCollapse") : t("orgChartExpand")}
            className="grid h-6 w-6 shrink-0 place-items-center rounded-md text-ink-muted transition hover:bg-surface-3 hover:text-ink"
          >
            <Icon name={open ? "expand_more" : "chevron_right"} size={18} />
          </button>
        ) : (
          <span className="grid h-6 w-6 shrink-0 place-items-center">
            <span className="h-1.5 w-1.5 rounded-full bg-border" />
          </span>
        )}
        <span
          className={`grid h-8 w-8 shrink-0 place-items-center rounded-full ${
            n ? "bg-brand/10 text-brand" : "bg-surface-3 text-ink-muted"
          }`}
        >
          <Icon name={n ? "person" : "account_tree"} size={18} />
        </span>
        <span className="min-w-0">
          <span className="block truncate text-sm font-medium text-ink">{label}</span>
          {subtitle && <span className="block truncate text-xs text-ink-muted">{subtitle}</span>}
        </span>
        {hasReports && (
          <span className="ml-auto shrink-0 text-xs text-ink-muted">
            {t("orgChartReports", { count: tn.reports.length })}
          </span>
        )}
      </div>
      {hasReports && open && (
        <ul>
          {tn.reports.map((child, i) => (
            <Row key={child.node?.id ?? `r-${i}`} tn={child} depth={depth + 1} />
          ))}
        </ul>
      )}
    </li>
  );
}

export default function OrgChart({ nodes }: { nodes: OrgChartNode[] }) {
  const t = useTranslations("admin");
  const tree = useMemo(() => buildTree(nodes), [nodes]);

  if (nodes.length === 0) {
    return (
      <EmptyState
        icon="account_tree"
        title={t("orgChartEmpty")}
        description={t("orgChartEmptyHint")}
      />
    );
  }

  return (
    <div className="card overflow-hidden p-2">
      <ul>
        {tree.reports.map((child, i) => (
          <Row key={child.node?.id ?? `top-${i}`} tn={child} depth={0} />
        ))}
      </ul>
    </div>
  );
}
