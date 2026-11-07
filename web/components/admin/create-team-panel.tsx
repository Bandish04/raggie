// SPDX-License-Identifier: Apache-2.0

"use client";

import { useTranslations } from "next-intl";
import { useActionState } from "react";

import { createTeamAction, type TeamActionState } from "@/app/admin/teams/actions";
import Select from "@/components/ui/select";
import type { TeamRow } from "@/lib/api";
import { ui } from "@/lib/ui";

export default function CreateTeamPanel({ teams }: { teams: TeamRow[] }) {
  const t = useTranslations("admin");
  const tc = useTranslations("common");
  const [state, action, pending] = useActionState<TeamActionState, FormData>(createTeamAction, {});

  return (
    <form action={action} className="card flex flex-wrap items-end gap-3 p-5">
      <div className="min-w-0 flex-1 space-y-1.5">
        <label className={ui.label}>{t("teamName")}</label>
        <input name="name" required placeholder="Engineering" className={ui.input} />
      </div>
      <div className="space-y-1.5">
        <label className={ui.label}>{t("parentTeam")}</label>
        <Select
          name="parent_team_id"
          defaultValue=""
          ariaLabel={t("parentTeam")}
          className="min-w-[13rem]"
          options={[
            { value: "", label: t("noParent") },
            ...teams.map((team) => ({ value: team.id, label: team.name })),
          ]}
        />
      </div>
      <button type="submit" disabled={pending} className={ui.btnPrimary}>
        {pending ? tc("loading") : t("createTeam")}
      </button>
      {state.error && <span className="w-full text-sm text-danger">{t("saveFailed")}</span>}
    </form>
  );
}
