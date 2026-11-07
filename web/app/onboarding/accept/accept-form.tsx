// SPDX-License-Identifier: Apache-2.0

"use client";

import { useTranslations } from "next-intl";
import { useActionState } from "react";

import { Badge } from "@/components/ui/badge";
import { Icon } from "@/components/ui/icon";
import Select from "@/components/ui/select";
import type { InvitePreview } from "@/lib/api";
import { PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH } from "@/lib/password-policy";
import { ui } from "@/lib/ui";

import { acceptInviteAction, type AcceptState } from "./actions";

function Field({
  label,
  name,
  defaultValue,
  type = "text",
  required = false,
  minLength,
  maxLength,
  hint,
}: {
  label: string;
  name: string;
  defaultValue?: string | null;
  type?: string;
  required?: boolean;
  minLength?: number;
  maxLength?: number;
  hint?: string;
}) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={name} className={ui.label}>
        {label}
      </label>
      <input
        id={name}
        name={name}
        type={type}
        required={required}
        minLength={minLength}
        maxLength={maxLength}
        aria-describedby={hint ? `${name}-hint` : undefined}
        defaultValue={defaultValue ?? ""}
        className={ui.input}
      />
      {hint && (
        <p id={`${name}-hint`} className="text-xs text-ink-muted">
          {hint}
        </p>
      )}
    </div>
  );
}

export default function AcceptForm({
  token,
  preview,
}: {
  token: string;
  preview: InvitePreview;
}) {
  const t = useTranslations("accept");
  const tc = useTranslations("common");
  const [state, action, pending] = useActionState<AcceptState, FormData>(
    acceptInviteAction,
    {},
  );

  const roleLabel =
    preview.role === "WORKSPACE_ADMIN" ? t("roleAdmin") : t("roleStaff");

  return (
    <form action={action} className="space-y-6">
      <input type="hidden" name="token" value={token} />

      {/* Who this invitation is for — the admin-seeded identity, shown warmly. */}
      <div className="rounded-2xl border border-border bg-surface-2/50 p-4">
        <div className="flex items-center gap-3">
          <span className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-brand/10 text-brand">
            <Icon name="account_circle" size={26} />
          </span>
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-ink">
              {preview.full_name || preview.email}
            </p>
            <p className="truncate text-xs text-ink-muted">{preview.email}</p>
          </div>
          <Badge tone="brand" className="ml-auto shrink-0">
            <Icon name="shield_person" size={14} />
            {roleLabel}
          </Badge>
        </div>
        {(preview.job_title || preview.department) && (
          <div className="mt-3 flex flex-wrap gap-1.5 border-t border-border pt-3">
            {preview.job_title && (
              <Badge tone="neutral">
                <Icon name="badge" size={14} />
                {preview.job_title}
              </Badge>
            )}
            {preview.department && (
              <Badge tone="neutral">
                <Icon name="apartment" size={14} />
                {preview.department}
              </Badge>
            )}
          </div>
        )}
      </div>

      <div className="space-y-3">
        <p className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
          {t("completeProfile")}
        </p>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t("fullName")} name="full_name" defaultValue={preview.full_name} />
          <Field label={t("jobTitle")} name="job_title" defaultValue={preview.job_title} />
          <Field label={t("department")} name="department" defaultValue={preview.department} />
          <Field label={t("phone")} name="phone" defaultValue={preview.phone} type="tel" />
          <Field label={t("location")} name="location" defaultValue={preview.location} />
          <div className="space-y-1.5">
            <label className={ui.label}>{t("locale")}</label>
            <Select
              name="locale"
              ariaLabel={t("locale")}
              defaultValue={preview.locale ?? "tr"}
              options={[
                { value: "tr", label: "Türkçe", icon: "language" },
                { value: "en", label: "English", icon: "language" },
              ]}
            />
          </div>
        </div>
      </div>

      <div className="space-y-3">
        <p className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
          {t("setPassword")}
        </p>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            label={t("password")}
            name="password"
            type="password"
            required
            minLength={PASSWORD_MIN_LENGTH}
            maxLength={PASSWORD_MAX_LENGTH}
            hint={tc("passwordHint", { min: PASSWORD_MIN_LENGTH })}
          />
          <Field
            label={t("confirmPassword")}
            name="confirm_password"
            type="password"
            required
            minLength={PASSWORD_MIN_LENGTH}
            maxLength={PASSWORD_MAX_LENGTH}
          />
        </div>
      </div>

      {state.error && (
        <p className="flex items-center gap-2 rounded-xl bg-danger/10 px-3.5 py-2.5 text-sm text-danger">
          <Icon name="error" size={18} />
          {state.error === "mismatch"
            ? t("passwordMismatch")
            : state.error === "short"
              ? t("passwordTooShort", { min: PASSWORD_MIN_LENGTH })
              : state.error === "policy"
                ? tc("passwordPolicyError", { min: PASSWORD_MIN_LENGTH, max: PASSWORD_MAX_LENGTH })
                : t("error")}
        </p>
      )}

      <button type="submit" disabled={pending} className={`${ui.btnPrimary} w-full py-3.5`}>
        {pending ? tc("loading") : t("finish")}
      </button>
    </form>
  );
}
