// SPDX-License-Identifier: Apache-2.0

"use client";

import { useTranslations } from "next-intl";

import { removeTeamMemberAction } from "@/app/admin/teams/actions";
import type { Member } from "@/lib/api";

export default function MemberTable({ teamId, members }: { teamId: string; members: Member[] }) {
  const t = useTranslations("admin");

  if (members.length === 0) {
    return <p className="px-1 py-3 text-sm text-ink-muted">{t("noMembers")}</p>;
  }

  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="border-b border-border text-left text-xs uppercase tracking-wider text-ink-muted">
          <th className="px-1 py-2 font-semibold">{t("colEmail")}</th>
          <th className="px-1 py-2 font-semibold">{t("colRole")}</th>
          <th className="px-1 py-2" />
        </tr>
      </thead>
      <tbody>
        {members.map((m) => (
          <tr key={m.id} className="border-b border-border/50 last:border-0">
            <td className="px-1 py-2.5 font-medium">{m.email}</td>
            <td className="px-1 py-2.5 text-ink-muted">{m.role}</td>
            <td className="px-1 py-2.5 text-right">
              <form action={removeTeamMemberAction}>
                <input type="hidden" name="team_id" value={teamId} />
                <input type="hidden" name="user_id" value={m.id} />
                <button
                  type="submit"
                  className="rounded-full px-3 py-1 text-xs font-medium text-danger transition hover:bg-danger/10"
                >
                  {t("remove")}
                </button>
              </form>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
