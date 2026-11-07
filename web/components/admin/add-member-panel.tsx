// SPDX-License-Identifier: Apache-2.0

"use client";

import { useTranslations } from "next-intl";
import { useActionState, useState } from "react";

import { addTeamMemberAction, type TeamActionState } from "@/app/admin/teams/actions";
import Select from "@/components/ui/select";
import type { OrgUser } from "@/lib/api";
import { ui } from "@/lib/ui";

export default function AddMemberPanel({
  teamId,
  users,
  existingIds,
}: {
  teamId: string;
  users: OrgUser[];
  existingIds: string[];
}) {
  const t = useTranslations("admin");
  const tc = useTranslations("common");
  const [state, action, pending] = useActionState<TeamActionState, FormData>(
    addTeamMemberAction,
    {},
  );
  const [userId, setUserId] = useState("");
  const available = users.filter((u) => !existingIds.includes(u.id));

  return (
    <form action={action} className="flex flex-wrap items-end gap-3">
      <input type="hidden" name="team_id" value={teamId} />
      <div className="min-w-0 flex-1 space-y-1.5">
        <label className={ui.label}>{t("addMember")}</label>
        <Select
          name="user_id"
          value={userId}
          onValueChange={setUserId}
          placeholder={t("selectUser")}
          ariaLabel={t("addMember")}
          className="w-full"
          options={available.map((u) => ({ value: u.id, label: u.email }))}
        />
      </div>
      <Select
        name="role"
        defaultValue="STAFF"
        ariaLabel={t("inviteRole")}
        className="min-w-[12rem]"
        options={[
          { value: "STAFF", label: t("roleStaff") },
          { value: "WORKSPACE_ADMIN", label: t("roleAdmin") },
        ]}
      />
      <button
        type="submit"
        disabled={pending || available.length === 0 || !userId}
        className={ui.btnPrimary}
      >
        {pending ? tc("loading") : t("addMember")}
      </button>
      {state.error && <span className="w-full text-sm text-danger">{t("saveFailed")}</span>}
    </form>
  );
}
