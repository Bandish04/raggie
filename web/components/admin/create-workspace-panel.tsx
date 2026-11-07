// SPDX-License-Identifier: Apache-2.0

"use client";

import { useTranslations } from "next-intl";
import { useActionState } from "react";

import { createWorkspaceAction, type WorkspaceActionState } from "@/app/admin/workspaces/actions";
import Select from "@/components/ui/select";
import type { TeamRow } from "@/lib/api";
import { ui } from "@/lib/ui";

export default function CreateWorkspacePanel({
  teams,
  defaultTeamId,
}: {
  teams: TeamRow[];
  defaultTeamId?: string;
}) {
  const t = useTranslations("admin");
  const tc = useTranslations("common");
  const [state, action, pending] = useActionState<WorkspaceActionState, FormData>(
    createWorkspaceAction,
    {},
  );

  return (
    <form action={action} className="card flex flex-wrap items-end gap-3 p-5">
      <div className="min-w-0 flex-1 space-y-1.5">
        <label className={ui.label}>{t("workspaceName")}</label>
        <input name="name" required placeholder="Support" className={ui.input} />
      </div>
      <div className="space-y-1.5">
        <label className={ui.label}>{t("workspaceType")}</label>
        <Select
          name="type"
          defaultValue="INTERNAL"
          ariaLabel={t("workspaceType")}
          className="min-w-[12rem]"
          options={[
            { value: "INTERNAL", label: t("typeInternal") },
            { value: "EXTERNAL", label: t("typeExternal") },
          ]}
        />
      </div>
      <div className="space-y-1.5">
        <label className={ui.label}>{t("assignTeam")}</label>
        <Select
          name="team_id"
          defaultValue={defaultTeamId ?? ""}
          ariaLabel={t("assignTeam")}
          className="min-w-[13rem]"
          options={[
            { value: "", label: t("noTeamOption") },
            ...teams.map((team) => ({ value: team.id, label: team.name })),
          ]}
        />
      </div>
      <label className="flex items-center gap-2 pb-1.5 text-sm text-ink-muted">
        <input type="checkbox" name="personalization_enabled" className="h-4 w-4 rounded border-border" />
        {t("personalization")}
      </label>
      <label className="flex items-center gap-2 pb-1.5 text-sm text-ink-muted">
        <input type="checkbox" name="web_search_enabled" className="h-4 w-4 rounded border-border" />
        {t("webSearch")}
      </label>
      <button type="submit" disabled={pending} className={ui.btnPrimary}>
        {pending ? tc("loading") : t("createWorkspace")}
      </button>
      {state.error && <span className="w-full text-sm text-danger">{t("saveFailed")}</span>}
    </form>
  );
}
