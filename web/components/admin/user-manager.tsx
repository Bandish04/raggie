// SPDX-License-Identifier: Apache-2.0

"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { Fragment, useActionState, useState, useTransition } from "react";

import {
  createUserAction,
  resetPassword,
  setPlatformAdminAction,
  setUserActive,
  updateUserAction,
  type UserFormState,
} from "@/app/admin/users/actions";
import Select from "@/components/ui/select";
import type { Department, Location, OrgUser } from "@/lib/api";
import { PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH } from "@/lib/password-policy";
import type { PlatformAdminError } from "@/lib/permissions";
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

function Field({
  label,
  name,
  defaultValue,
  type = "text",
  required = false,
  minLength,
  maxLength,
  autoComplete,
  hint,
}: {
  label: string;
  name: string;
  defaultValue?: string | null;
  type?: string;
  required?: boolean;
  minLength?: number;
  maxLength?: number;
  autoComplete?: string;
  hint?: string;
}) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={`f-${name}`} className={ui.label}>
        {label}
      </label>
      <input
        id={`f-${name}`}
        name={name}
        type={type}
        required={required}
        minLength={minLength}
        maxLength={maxLength}
        autoComplete={autoComplete}
        aria-describedby={hint ? `f-${name}-hint` : undefined}
        defaultValue={defaultValue ?? ""}
        className={ui.input}
      />
      {hint && (
        <p id={`f-${name}-hint`} className="text-xs text-ink-muted">
          {hint}
        </p>
      )}
    </div>
  );
}

/** Shared profile inputs for both the create and edit forms. */
function ProfileFields({
  user,
  users,
  departments,
  locations,
  canSuper,
}: {
  user?: OrgUser;
  users: OrgUser[];
  departments: Department[];
  locations: Location[];
  canSuper: boolean;
}) {
  const t = useTranslations("admin");
  // Stored zone, else the browser's, else UTC; `key` remounts the uncontrolled select.
  const timezone = useResolvedTimezone(user?.timezone);
  const roleOptions = [
    { value: "STAFF", label: t("roleStaff"), icon: "person" },
    { value: "WORKSPACE_ADMIN", label: t("roleAdmin"), icon: "shield_person" },
    ...(canSuper
      ? [{ value: "SUPER_ADMIN", label: "Super admin", icon: "admin_panel_settings" }]
      : []),
  ];
  const managerOptions = [
    { value: "", label: t("managerNone"), icon: "block" },
    ...users
      .filter((u) => u.id !== user?.id)
      .map((u) => ({ value: u.id, label: u.full_name || u.email, icon: "person" })),
  ];
  // Managed directory selects — the form sends department_id / location_id and
  // the backend write-through fills the legacy department TEXT automatically.
  const departmentOptions = [
    { value: "", label: t("dirDepartmentNone"), icon: "block" },
    ...departments.map((d) => ({ value: d.id, label: d.name, icon: "apartment" })),
  ];
  const locationOptions = [
    { value: "", label: t("dirLocationNone"), icon: "block" },
    ...locations.map((l) => ({ value: l.id, label: l.name, icon: "location_on" })),
  ];
  return (
    <>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-1.5">
          <label className={ui.label}>{t("colRole")}</label>
          <Select
            name="role"
            ariaLabel={t("colRole")}
            defaultValue={user?.role ?? "STAFF"}
            options={roleOptions}
          />
        </div>
        <div className="space-y-1.5">
          <label className={ui.label}>{t("manager")}</label>
          <Select
            name="manager_user_id"
            ariaLabel={t("manager")}
            defaultValue={user?.manager_user_id ?? ""}
            options={managerOptions}
          />
        </div>
        <Field label={t("fullName")} name="full_name" defaultValue={user?.full_name} />
        <Field label={t("jobTitle")} name="job_title" defaultValue={user?.job_title} />
        <div className="space-y-1.5">
          <label className={ui.label}>{t("department")}</label>
          <Select
            name="department_id"
            ariaLabel={t("department")}
            defaultValue={user?.department_id ?? ""}
            options={departmentOptions}
          />
        </div>
        <div className="space-y-1.5">
          <label className={ui.label}>{t("location")}</label>
          <Select
            name="location_id"
            ariaLabel={t("location")}
            defaultValue={user?.location_id ?? ""}
            options={locationOptions}
          />
        </div>
        <Field label={t("hireDate")} name="hire_date" type="date" defaultValue={user?.hire_date} />
        <Field label={t("phone")} name="phone" type="tel" defaultValue={user?.phone} />
        <div className="space-y-1.5">
          <label className={ui.label}>{t("timezone")}</label>
          <Select
            name="timezone"
            ariaLabel={t("timezone")}
            key={timezone}
            defaultValue={timezone}
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
            ariaLabel={t("locale")}
            defaultValue={user?.locale ?? "tr"}
            options={[
              { value: "tr", label: "Türkçe", icon: "language" },
              { value: "en", label: "English", icon: "language" },
            ]}
          />
        </div>
      </div>
    </>
  );
}

function CreatePanel({
  users,
  departments,
  locations,
  canSuper,
  onDone,
}: {
  users: OrgUser[];
  departments: Department[];
  locations: Location[];
  canSuper: boolean;
  onDone: () => void;
}) {
  const t = useTranslations("admin");
  const tc = useTranslations("common");
  const [state, action, pending] = useActionState<UserFormState, FormData>(
    createUserAction,
    {},
  );
  return (
    <form action={action} className="card space-y-4 p-6">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t("inviteEmail")} name="email" type="email" required />
        {/* Optional: left blank, the control plane generates a temp password.
            minLength only applies once something is typed. */}
        <Field
          label={t("passwordOptional")}
          name="password"
          type="password"
          autoComplete="new-password"
          minLength={PASSWORD_MIN_LENGTH}
          maxLength={PASSWORD_MAX_LENGTH}
          hint={tc("passwordHint", { min: PASSWORD_MIN_LENGTH })}
        />
      </div>
      <ProfileFields
        users={users}
        departments={departments}
        locations={locations}
        canSuper={canSuper}
      />
      <div className="flex items-center gap-3">
        <button type="submit" disabled={pending} className={ui.btnPrimary}>
          {pending ? tc("loading") : t("createUser")}
        </button>
        <button type="button" onClick={onDone} className={ui.btnGhost}>
          {tc("cancel")}
        </button>
        {state.error && <span className="text-sm text-danger">{t("saveError")}</span>}
        {state.passwordError && (
          <span className="text-sm text-danger">
            {tc("passwordPolicyError", { min: PASSWORD_MIN_LENGTH, max: PASSWORD_MAX_LENGTH })}
          </span>
        )}
      </div>
      {state.ok && state.tempPassword && (
        <div className="rounded-xl border border-brand/30 bg-brand/5 p-4 text-sm">
          <p className="font-medium text-ink">{t("tempPassword")}</p>
          <code className="mt-1 block break-all text-brand">{state.tempPassword}</code>
          <p className="mt-1 text-xs text-ink-muted">{t("tempPasswordOnce")}</p>
        </div>
      )}
      {state.ok && !state.tempPassword && (
        <p className="text-sm text-success">{t("saved")}</p>
      )}
    </form>
  );
}

function EditPanel({
  user,
  users,
  departments,
  locations,
  canSuper,
  onDone,
}: {
  user: OrgUser;
  users: OrgUser[];
  departments: Department[];
  locations: Location[];
  canSuper: boolean;
  onDone: () => void;
}) {
  const t = useTranslations("admin");
  const tc = useTranslations("common");
  const [state, action, pending] = useActionState<UserFormState, FormData>(
    updateUserAction,
    {},
  );
  return (
    <form action={action} className="card space-y-4 p-6">
      <input type="hidden" name="user_id" value={user.id} />
      <p className="text-sm font-medium text-ink">{user.email}</p>
      <ProfileFields
        user={user}
        users={users}
        departments={departments}
        locations={locations}
        canSuper={canSuper}
      />
      <div className="flex items-center gap-3">
        <button type="submit" disabled={pending} className={ui.btnPrimary}>
          {pending ? tc("loading") : tc("save")}
        </button>
        <button type="button" onClick={onDone} className={ui.btnGhost}>
          {tc("cancel")}
        </button>
        {state.ok && <span className="text-sm text-success">{t("saved")}</span>}
        {state.error && <span className="text-sm text-danger">{t("saveError")}</span>}
      </div>
    </form>
  );
}

export default function UserManager({
  users,
  departments,
  locations,
  canManageSuperAdmin,
  canManagePlatformAdmin = false,
}: {
  users: OrgUser[];
  departments: Department[];
  locations: Location[];
  canManageSuperAdmin: boolean;
  // Viewer is a platform admin: may grant/revoke platform-admin on others.
  canManagePlatformAdmin?: boolean;
}) {
  const t = useTranslations("admin");
  const router = useRouter();
  const [platformError, setPlatformError] = useState<PlatformAdminError | null>(null);
  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [resetFor, setResetFor] = useState<{ id: string; pw: string } | null>(null);
  const [pending, start] = useTransition();

  function toggleActive(u: OrgUser) {
    start(async () => {
      await setUserActive(u.id, !u.is_active);
      router.refresh();
    });
  }
  function togglePlatformAdmin(u: OrgUser) {
    setPlatformError(null);
    start(async () => {
      const res = await setPlatformAdminAction(u.id, !u.is_platform_admin);
      if (!res.ok) setPlatformError(res.error ?? "generic");
      else router.refresh();
    });
  }
  function doReset(u: OrgUser) {
    start(async () => {
      const res = await resetPassword(u.id);
      if (res.ok && res.tempPassword) setResetFor({ id: u.id, pw: res.tempPassword });
    });
  }

  return (
    <div className="space-y-6">
      <div className="flex justify-end">
        {!creating && (
          <button
            type="button"
            onClick={() => {
              setCreating(true);
              setEditingId(null);
            }}
            className={ui.btnPrimary}
          >
            <span className="material-symbols-outlined text-[18px]">add</span>
            {t("createUser")}
          </button>
        )}
      </div>

      {creating && (
        <CreatePanel
          users={users}
          departments={departments}
          locations={locations}
          canSuper={canManageSuperAdmin}
          onDone={() => setCreating(false)}
        />
      )}

      {resetFor && (
        <div className="rounded-xl border border-brand/30 bg-brand/5 p-4 text-sm">
          <p className="font-medium text-ink">{t("tempPassword")}</p>
          <code className="mt-1 block break-all text-brand">{resetFor.pw}</code>
          <p className="mt-1 text-xs text-ink-muted">{t("tempPasswordOnce")}</p>
          <button
            type="button"
            onClick={() => setResetFor(null)}
            className="mt-2 grid h-7 w-7 place-items-center rounded-lg text-ink-muted hover:bg-surface-2"
            aria-label="Dismiss"
          >
            <span className="material-symbols-outlined text-[18px]">close</span>
          </button>
        </div>
      )}

      {platformError && (
        <p role="alert" className="rounded-xl bg-danger/10 px-3.5 py-2.5 text-sm text-danger">
          {platformError === "lastAdmin"
            ? t("platformAdminLast")
            : platformError === "requiresSuperAdmin"
              ? t("platformAdminNeedsSuper")
              : platformError === "forbidden"
                ? t("platformAdminForbidden")
                : t("platformAdminFailed")}
        </p>
      )}

      <div className="card overflow-hidden">
        {users.length === 0 ? (
          <p className="p-6 text-sm text-ink-muted">{t("noUsers")}</p>
        ) : (
          <table className="w-full text-sm">
            <thead className="border-b border-border text-left text-xs uppercase tracking-wide text-ink-muted">
              <tr>
                <th className="px-4 py-3">{t("colEmail")}</th>
                <th className="px-4 py-3">{t("fullName")}</th>
                <th className="px-4 py-3">{t("department")}</th>
                <th className="px-4 py-3">{t("manager")}</th>
                <th className="px-4 py-3">{t("colRole")}</th>
                <th className="px-4 py-3">{t("colStatus")}</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {users.map((u) => (
                <Fragment key={u.id}>
                  <tr className="hover:bg-surface-2/40">
                    <td className="px-4 py-3">{u.email}</td>
                    <td className="px-4 py-3 text-ink-muted">{u.full_name ?? "—"}</td>
                    <td className="px-4 py-3 text-ink-muted">{u.department ?? "—"}</td>
                    <td className="px-4 py-3 text-ink-muted">{u.manager_display ?? "—"}</td>
                    <td className="px-4 py-3">
                      <span className="inline-flex flex-wrap items-center gap-1.5">
                        {u.role}
                        {u.is_platform_admin && (
                          <span className="inline-flex items-center rounded-full bg-brand/10 px-2 py-0.5 text-xs font-medium text-brand">
                            {t("platformAdminBadge")}
                          </span>
                        )}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs ${
                          u.is_active
                            ? "bg-success/10 text-success"
                            : "bg-surface-3 text-ink-muted"
                        }`}
                      >
                        {u.is_active ? t("statusActive") : t("statusInactive")}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center justify-end gap-1">
                        <button
                          type="button"
                          title={t("editUser")}
                          onClick={() =>
                            setEditingId((id) => (id === u.id ? null : u.id))
                          }
                          className="grid h-8 w-8 place-items-center rounded-lg text-ink-muted hover:bg-surface-2 hover:text-ink"
                        >
                          <span className="material-symbols-outlined text-[18px]">edit</span>
                        </button>
                        {canManagePlatformAdmin && (
                          <button
                            type="button"
                            title={u.is_platform_admin ? t("platformAdminRevoke") : t("platformAdminGrant")}
                            aria-label={u.is_platform_admin ? t("platformAdminRevoke") : t("platformAdminGrant")}
                            aria-pressed={!!u.is_platform_admin}
                            disabled={pending}
                            onClick={() => togglePlatformAdmin(u)}
                            className={`grid h-8 w-8 place-items-center rounded-lg hover:bg-surface-2 ${
                              u.is_platform_admin ? "text-brand" : "text-ink-muted hover:text-ink"
                            }`}
                          >
                            <span className="material-symbols-outlined text-[18px]">
                              {u.is_platform_admin ? "verified_user" : "add_moderator"}
                            </span>
                          </button>
                        )}
                        <button
                          type="button"
                          title={t("resetPassword")}
                          disabled={pending}
                          onClick={() => doReset(u)}
                          className="grid h-8 w-8 place-items-center rounded-lg text-ink-muted hover:bg-surface-2 hover:text-ink"
                        >
                          <span className="material-symbols-outlined text-[18px]">key</span>
                        </button>
                        <button
                          type="button"
                          title={u.is_active ? t("deactivate") : t("reactivate")}
                          disabled={pending}
                          onClick={() => toggleActive(u)}
                          className="grid h-8 w-8 place-items-center rounded-lg text-ink-muted hover:bg-surface-2 hover:text-ink"
                        >
                          <span className="material-symbols-outlined text-[18px]">
                            {u.is_active ? "person_off" : "person_check"}
                          </span>
                        </button>
                      </div>
                    </td>
                  </tr>
                  {editingId === u.id && (
                    <tr>
                      <td colSpan={7} className="bg-surface-2/30 p-4">
                        <EditPanel
                          user={u}
                          users={users}
                          departments={departments}
                          locations={locations}
                          canSuper={canManageSuperAdmin}
                          onDone={() => setEditingId(null)}
                        />
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
