// SPDX-License-Identifier: Apache-2.0

"use client";

import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useActionState, useState, useTransition } from "react";

import {
  createInviteAction,
  type InviteState,
  resendInviteAction,
  revokeInviteAction,
} from "@/app/admin/team/actions";
import Select from "@/components/ui/select";
import type {
  Department,
  InviteListItem,
  Location,
  OrgUser,
  TeamRow,
  WorkspaceRow,
} from "@/lib/api";
import { ui } from "@/lib/ui";
import { useResolvedTimezone } from "@/lib/use-resolved-timezone";

const TIMEZONES = [
  "Europe/Istanbul",
  "Europe/London",
  "Europe/Berlin",
  "America/New_York",
  "America/Los_Angeles",
  "Asia/Dubai",
  "UTC",
];

function absolute(path?: string): string {
  if (!path) return "";
  return (typeof window !== "undefined" ? window.location.origin : "") + path;
}

function CopyRow({ link, label }: { link: string; label: string }) {
  const tc = useTranslations("common");
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      /* clipboard unavailable */
    }
  }
  return (
    <div className="space-y-1.5">
      {label && <p className="text-sm font-medium text-ink">{label}</p>}
      <div className="flex items-center gap-2 rounded-xl border border-border bg-surface-2 p-2 pl-4">
        <code className="min-w-0 flex-1 truncate text-xs text-ink-muted">{link}</code>
        <button type="button" onClick={copy} className={ui.btnPrimary}>
          {copied ? tc("copied") : tc("copy")}
        </button>
      </div>
    </div>
  );
}

export default function InvitePanel({
  teamId,
  workspaceId,
  teams,
  workspaces,
  invites,
  users,
  departments,
  locations,
}: {
  teamId?: string;
  workspaceId?: string;
  teams?: TeamRow[];
  workspaces?: WorkspaceRow[];
  invites?: InviteListItem[];
  users?: OrgUser[];
  departments?: Department[];
  locations?: Location[];
} = {}) {
  const t = useTranslations("admin");
  const locale = useLocale();
  const tc = useTranslations("common");
  const [state, action, pending] = useActionState<InviteState, FormData>(createInviteAction, {});
  const [showProfile, setShowProfile] = useState(false);
  // An invitee has no stored zone yet: default to the admin's browser zone, else UTC.
  const timezone = useResolvedTimezone(null);
  const [resent, setResent] = useState<Record<string, string>>({});
  const [busy, start] = useTransition();
  const router = useRouter();

  const link = state.ok ? absolute(state.acceptPath) : "";
  const showTeamSelect = !teamId && teams && teams.length > 0;
  const showWorkspaceSelect = !workspaceId && workspaces && workspaces.length > 0;
  const managerOptions = [
    { value: "", label: t("managerNone"), icon: "block" },
    ...(users ?? []).map((u) => ({
      value: u.id,
      label: u.full_name || u.email,
      icon: "person",
    })),
  ];
  // Department/location are seeded as TEXT (the value the chat persona reads), so
  // the option value is the managed name — picked from the directory, blank allowed.
  const departmentOptions = [
    { value: "", label: t("dirDepartmentNone"), icon: "block" },
    ...(departments ?? []).map((d) => ({ value: d.name, label: d.name, icon: "apartment" })),
  ];
  const locationOptions = [
    { value: "", label: t("dirLocationNone"), icon: "block" },
    ...(locations ?? []).map((l) => ({ value: l.name, label: l.name, icon: "location_on" })),
  ];

  function statusLabel(s: InviteListItem["status"]): string {
    return {
      pending: t("statusPending"),
      accepted: t("statusAccepted"),
      revoked: t("statusRevoked"),
      expired: t("statusExpired"),
    }[s];
  }

  function onRevoke(id: string) {
    start(async () => {
      await revokeInviteAction(id);
      router.refresh();
    });
  }
  function onResend(id: string) {
    start(async () => {
      const res = await resendInviteAction(id);
      if (res.ok && res.acceptPath) {
        setResent((m) => ({ ...m, [id]: absolute(res.acceptPath) }));
      }
      router.refresh();
    });
  }

  return (
    <div className="space-y-8">
      <form action={action} className="card space-y-4 p-6">
        {teamId && <input type="hidden" name="team_id" value={teamId} />}
        {workspaceId && <input type="hidden" name="workspace_id" value={workspaceId} />}

        <div className="space-y-1.5">
          <label htmlFor="email" className={ui.label}>
            {t("inviteEmail")}
          </label>
          <input
            id="email"
            name="email"
            type="email"
            required
            placeholder="teammate@example.com"
            className={ui.input}
          />
        </div>

        {(showTeamSelect || showWorkspaceSelect) && (
          <div className="grid gap-4 sm:grid-cols-2">
            {showTeamSelect && (
              <div className="space-y-1.5">
                <label className={ui.label}>{t("assignTeam")}</label>
                <Select
                  name="team_id"
                  defaultValue=""
                  ariaLabel={t("assignTeam")}
                  className="w-full"
                  options={[
                    { value: "", label: t("noTeamOption"), icon: "block" },
                    ...teams!.map((tm) => ({ value: tm.id, label: tm.name, icon: "groups" })),
                  ]}
                />
              </div>
            )}
            {showWorkspaceSelect && (
              <div className="space-y-1.5">
                <label className={ui.label}>{t("chooseWorkspace")}</label>
                <Select
                  name="workspace_id"
                  defaultValue=""
                  ariaLabel={t("chooseWorkspace")}
                  className="w-full"
                  options={[
                    { value: "", label: t("noWorkspaceOption"), icon: "block" },
                    ...workspaces!.map((w) => ({ value: w.id, label: w.name, icon: "workspaces" })),
                  ]}
                />
              </div>
            )}
          </div>
        )}

        <div className="space-y-1.5">
          <label htmlFor="role" className={ui.label}>
            {t("inviteRole")}
          </label>
          <Select
            id="role"
            name="role"
            defaultValue="STAFF"
            ariaLabel={t("inviteRole")}
            options={[
              { value: "STAFF", label: t("roleStaff"), icon: "person" },
              { value: "WORKSPACE_ADMIN", label: t("roleAdmin"), icon: "shield_person" },
            ]}
          />
        </div>

        {/* Collapsible "seed this person's profile" panel. Everything here is
            optional and carried on the invite; the invitee can adjust blanks. */}
        <div className="rounded-2xl border border-border bg-surface-2/40">
          <button
            type="button"
            onClick={() => setShowProfile((s) => !s)}
            aria-expanded={showProfile}
            className="flex w-full items-start gap-3 p-4 text-left transition hover:bg-surface-2/60"
          >
            <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-full bg-brand/10 text-brand">
              <span className="material-symbols-outlined text-[20px]">badge</span>
            </span>
            <span className="min-w-0 flex-1">
              <span className="block text-sm font-semibold text-ink">{t("prefillProfile")}</span>
              <span className="mt-0.5 block text-xs text-ink-muted">{t("prefillProfileHint")}</span>
            </span>
            <span className="material-symbols-outlined mt-0.5 text-[20px] text-ink-muted">
              {showProfile ? "expand_less" : "expand_more"}
            </span>
          </button>

          {showProfile && (
            <div className="grid gap-4 border-t border-border p-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <label htmlFor="full_name" className={ui.label}>
                  {t("fullName")}
                </label>
                <input id="full_name" name="full_name" className={ui.input} />
              </div>
              <div className="space-y-1.5">
                <label htmlFor="job_title" className={ui.label}>
                  {t("jobTitle")}
                </label>
                <input id="job_title" name="job_title" className={ui.input} />
              </div>
              <div className="space-y-1.5">
                <label className={ui.label}>{t("department")}</label>
                <Select
                  name="department"
                  defaultValue=""
                  ariaLabel={t("department")}
                  options={departmentOptions}
                />
              </div>
              <div className="space-y-1.5">
                <label className={ui.label}>{t("manager")}</label>
                <Select
                  name="manager_user_id"
                  defaultValue=""
                  ariaLabel={t("manager")}
                  options={managerOptions}
                />
              </div>
              <div className="space-y-1.5">
                <label htmlFor="phone" className={ui.label}>
                  {t("phone")}
                </label>
                <input id="phone" name="phone" type="tel" className={ui.input} />
              </div>
              <div className="space-y-1.5">
                <label className={ui.label}>{t("location")}</label>
                <Select
                  name="location"
                  defaultValue=""
                  ariaLabel={t("location")}
                  options={locationOptions}
                />
              </div>
              <div className="space-y-1.5">
                <label className={ui.label}>{t("timezone")}</label>
                <Select
                  name="timezone"
                  key={timezone}
                  defaultValue={timezone}
                  ariaLabel={t("timezone")}
                  options={Array.from(new Set([timezone, ...TIMEZONES])).map((tz) => ({
                    value: tz,
                    label: tz,
                    icon: "schedule",
                  }))}
                />
              </div>
              <div className="space-y-1.5">
                <label className={ui.label}>{t("locale")}</label>
                <Select
                  name="locale"
                  defaultValue="tr"
                  ariaLabel={t("locale")}
                  options={[
                    { value: "tr", label: "Türkçe", icon: "language" },
                    { value: "en", label: "English", icon: "language" },
                  ]}
                />
              </div>
            </div>
          )}
        </div>

        {state.error && (
          <p className="rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger" role="alert">
            {t("inviteError")}
          </p>
        )}
        <button type="submit" disabled={pending} className={`${ui.btnPrimary} w-full`}>
          {pending ? tc("loading") : t("createInvite")}
        </button>
      </form>

      {link && (
        <div className="card animate-fade-up p-6">
          <CopyRow link={link} label={t("inviteCreated")} />
        </div>
      )}

      {/* Pending invites */}
      {invites && (
        <div className="card overflow-hidden">
          <div className="border-b border-border px-6 py-4">
            <h2 className="font-display text-lg font-semibold">{t("pendingInvites")}</h2>
          </div>
          {invites.length === 0 ? (
            <p className="p-6 text-sm text-ink-muted">{t("noInvites")}</p>
          ) : (
            <table className="w-full text-sm">
              <thead className="border-b border-border text-left text-xs uppercase tracking-wide text-ink-muted">
                <tr>
                  <th className="px-4 py-3">{t("colEmail")}</th>
                  <th className="px-4 py-3">{t("colStatus")}</th>
                  <th className="px-4 py-3">{t("expires")}</th>
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {invites.map((i) => (
                  <tr key={i.id} className="align-top hover:bg-surface-2/40">
                    <td className="px-4 py-3">
                      <div>{i.email}</div>
                      {i.full_name && (
                        <div className="text-xs text-ink-muted">{i.full_name}</div>
                      )}
                      {resent[i.id] && (
                        <div className="mt-2 max-w-md">
                          <CopyRow link={resent[i.id]} label={t("copyLink")} />
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <span className="inline-flex items-center rounded-full bg-surface-3 px-2 py-0.5 text-xs text-ink-muted">
                        {statusLabel(i.status)}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-ink-muted">
                      {new Date(i.expires_at).toLocaleDateString(locale)}
                    </td>
                    <td className="px-4 py-3">
                      {i.status === "pending" && (
                        <div className="flex items-center justify-end gap-1">
                          <button
                            type="button"
                            title={t("resend")}
                            disabled={busy}
                            onClick={() => onResend(i.id)}
                            className="grid h-8 w-8 place-items-center rounded-lg text-ink-muted hover:bg-surface-2 hover:text-ink"
                          >
                            <span className="material-symbols-outlined text-[18px]">forward_to_inbox</span>
                          </button>
                          <button
                            type="button"
                            title={t("revoke")}
                            disabled={busy}
                            onClick={() => onRevoke(i.id)}
                            className="grid h-8 w-8 place-items-center rounded-lg text-ink-muted hover:bg-surface-2 hover:text-danger"
                          >
                            <span className="material-symbols-outlined text-[18px]">link_off</span>
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}
