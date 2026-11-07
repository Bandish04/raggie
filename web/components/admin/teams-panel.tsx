// SPDX-License-Identifier: Apache-2.0

"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";

import CreateTeamPanel from "@/components/admin/create-team-panel";
import type { TeamRow } from "@/lib/api";

// Flatten the parent/child team graph into a depth-ordered list for rendering.
// Kept identical to the original standalone /admin/teams page so the Teams tab
// in the consolidated Organization page behaves exactly the same.
function flatten(teams: TeamRow[]): { team: TeamRow; depth: number }[] {
  const byParent = new Map<string | null, TeamRow[]>();
  for (const t of teams) {
    const arr = byParent.get(t.parent_team_id) ?? [];
    arr.push(t);
    byParent.set(t.parent_team_id, arr);
  }
  const out: { team: TeamRow; depth: number }[] = [];
  const walk = (parent: string | null, depth: number) => {
    for (const team of byParent.get(parent) ?? []) {
      out.push({ team, depth });
      walk(team.id, depth + 1);
    }
  };
  walk(null, 0);
  return out;
}

/**
 * The body of the former /admin/teams page, extracted verbatim so it can be
 * dropped into the Organization tab container. Client-component-free on its own
 * (it renders the client `CreateTeamPanel`); data arrives as a prop.
 */
export default function TeamsPanel({ teams }: { teams: TeamRow[] }) {
  const t = useTranslations("admin");
  const nodes = flatten(teams);

  return (
    <>
      <CreateTeamPanel teams={teams} />

      <div className="card mt-5 overflow-hidden p-2">
        {nodes.length === 0 ? (
          <p className="px-4 py-10 text-center text-sm text-ink-muted">{t("noTeams")}</p>
        ) : (
          <ul>
            {nodes.map(({ team, depth }) => (
              <li key={team.id}>
                <Link
                  href={`/admin/teams/${team.id}`}
                  className="flex items-center gap-2 rounded-xl px-3 py-2.5 text-sm transition hover:bg-surface-2"
                  style={{ paddingLeft: `${0.75 + depth * 1.25}rem` }}
                >
                  <span className="material-symbols-outlined text-base text-ink-muted">groups</span>
                  <span className="font-medium">{team.name}</span>
                  <span className="material-symbols-outlined ml-auto text-base text-ink-muted">
                    chevron_right
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  );
}
