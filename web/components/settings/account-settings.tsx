// SPDX-License-Identifier: Apache-2.0

"use client";

import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useActionState, useEffect, useState, useTransition } from "react";

import { setLocale } from "@/app/actions/locale";
import {
  changePasswordAction,
  clearMemoryAction,
  importMemoryAction,
  type MemoryImportState,
  type PasswordFormState,
  type PreferencesFormState,
  type ProfileFormState,
  updatePreferencesAction,
  updateProfileAction,
} from "@/app/account/actions";
import { Icon } from "@/components/ui/icon";
import Select from "@/components/ui/select";
import { copyToClipboard } from "@/lib/clipboard";
import { useResolvedTimezone } from "@/lib/use-resolved-timezone";
import type { MemoryItem, ModelsConfig, ProfileResponse } from "@/lib/api";
import { PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH } from "@/lib/password-policy";
import { ui } from "@/lib/ui";

// The four settings sections, in display order. Shared between the standalone
// /account page (rendered stacked) and the chat settings modal (rendered one at
// a time via the left tab rail). Keeping this list here is the single source of
// truth so the page and the modal never drift apart.
export type SettingsTab = "profile" | "security" | "preferences" | "memory";

/** Tab metadata (label key under `account`, Material icon) for the modal rail. */
export const SETTINGS_TABS: { id: SettingsTab; labelKey: string; icon: string }[] = [
  { id: "profile", labelKey: "profile", icon: "person" },
  { id: "security", labelKey: "security", icon: "lock" },
  { id: "preferences", labelKey: "preferencesTitle", icon: "tune" },
  { id: "memory", labelKey: "memory", icon: "neurology" },
];

const TIMEZONES = [
  "Europe/Istanbul",
  "Europe/London",
  "Europe/Berlin",
  "America/New_York",
  "America/Los_Angeles",
  "Asia/Dubai",
  "UTC",
];

/** A labeled text input used across the profile & security forms. */
function Field({
  label,
  name,
  defaultValue,
  type = "text",
  autoComplete,
  minLength,
  maxLength,
  hint,
}: {
  label: string;
  name: string;
  defaultValue?: string | null;
  type?: string;
  autoComplete?: string;
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
        autoComplete={autoComplete}
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

/** A read-only profile fact (email, manager, tenure) rendered as a calm inset row. */
function ReadOnlyField({ label, value }: { label: string; value: string }) {
  return (
    <div className="space-y-1.5">
      <span className={ui.label}>{label}</span>
      <p className="flex min-h-10 items-center rounded-xl bg-surface-2 px-3.5 text-sm text-ink-muted">
        {value}
      </p>
    </div>
  );
}

/**
 * Section shell. Two layouts from ONE definition:
 *  - "page": a quiet heading + supporting line in a left rail over open space,
 *    with a hairline rule between sections — the calm editorial /account rhythm.
 *    `anchor` becomes the element id (e.g. #preferences) so deep links keep working.
 *  - "modal": a single tab pane — a compact heading stacked above the body, no
 *    left rail or section divider (the modal's tab rail already provides nav).
 */
function Section({
  variant,
  anchor,
  title,
  description,
  children,
}: {
  variant: SettingsVariant;
  anchor?: string;
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  if (variant === "modal") {
    return (
      <section className="space-y-6">
        <div>
          <h2 className="font-display text-lg font-semibold tracking-tight">{title}</h2>
          <p className="mt-1 text-sm leading-relaxed text-ink-muted">{description}</p>
        </div>
        <div className="min-w-0">{children}</div>
      </section>
    );
  }
  return (
    <section
      id={anchor}
      className="scroll-mt-24 border-t border-border pt-10 first:border-t-0 first:pt-0"
    >
      <div className="grid gap-x-12 gap-y-6 md:grid-cols-[14rem_minmax(0,1fr)]">
        <div className="md:pt-1">
          <h2 className="font-display text-lg font-semibold tracking-tight">{title}</h2>
          <p className="mt-1 text-sm leading-relaxed text-ink-muted">{description}</p>
        </div>
        <div className="min-w-0">{children}</div>
      </div>
    </section>
  );
}

/** Inline confirmation / error line shared by every form's action row. */
function FormStatus({ ok, okLabel, error }: { ok?: boolean; okLabel: string; error?: React.ReactNode }) {
  if (ok) {
    return (
      <span className="inline-flex items-center gap-1.5 text-sm text-success">
        <Icon name="check_circle" size={16} fill />
        {okLabel}
      </span>
    );
  }
  if (error) return <span className="text-sm text-danger">{error}</span>;
  return null;
}

export type SettingsVariant = "page" | "modal";

/**
 * The account/settings body. Single source of truth for the four sections used
 * by both the standalone /account page (`variant="page"`, all sections stacked)
 * and the chat settings modal (`variant="modal"`, one `activeTab` at a time).
 * Keeps the existing server actions and refreshes the host (`router.refresh()`)
 * after every successful mutation so the re-fetched data flows back in.
 */
export default function AccountSettings({
  profile,
  email,
  memory = [],
  models,
  variant = "page",
  activeTab,
}: {
  profile: ProfileResponse | null;
  email: string;
  memory?: MemoryItem[];
  models: ModelsConfig;
  variant?: SettingsVariant;
  // Modal only: which single section to render. Ignored in "page" variant.
  activeTab?: SettingsTab;
}) {
  const t = useTranslations("account");
  const tc = useTranslations("common");
  const u = profile?.user;
  const router = useRouter();

  // Language: drive the existing locale server action directly (the segmented
  // LocaleSwitcher pill was replaced by a design-system Select for consistency
  // with the other preference controls).
  const locale = useLocale();
  const [localePending, startLocale] = useTransition();
  function changeLocale(value: string) {
    if (value === locale || localePending) return;
    startLocale(async () => {
      await setLocale(value as "tr" | "en");
      router.refresh(); // re-render the RSC tree in the new locale — no full reload
    });
  }

  // Stored zone, else the browser's (hydration-safe), else UTC. The select is
  // uncontrolled, so `key` remounts it once the browser zone is known.
  const timezone = useResolvedTimezone(u?.timezone);

  const [clearing, startClear] = useTransition();
  const [cleared, setCleared] = useState(false);
  function clearMemory() {
    startClear(async () => {
      const ok = await clearMemoryAction();
      if (ok) {
        setCleared(true);
        router.refresh();
      }
    });
  }

  const [pState, pAction, pPending] = useActionState<ProfileFormState, FormData>(
    updateProfileAction,
    {},
  );
  const [secState, secAction, secPending] = useActionState<PasswordFormState, FormData>(
    changePasswordAction,
    {},
  );
  const [prefState, prefAction, prefPending] = useActionState<PreferencesFormState, FormData>(
    updatePreferencesAction,
    {},
  );

  // Pull fresh server data back into the host after a successful profile or
  // preferences save. The actions already revalidate /account; refreshing here
  // updates the modal (whose data is a prop) and the page alike.
  useEffect(() => {
    if (pState.ok) router.refresh();
  }, [pState.ok, router]);
  useEffect(() => {
    if (prefState.ok) router.refresh();
  }, [prefState.ok, router]);

  // Memory import: panel disclosure, prompt-copy check state, and the action.
  const [importOpen, setImportOpen] = useState(false);
  const [promptCopied, setPromptCopied] = useState(false);
  const [importState, importAction, importPending] = useActionState<MemoryImportState, FormData>(
    importMemoryAction,
    {},
  );

  // The prompt the user copies into another assistant (ChatGPT/Claude/Gemini/
  // Grok) to produce a memory summary they can paste back here. Localized per UI
  // language; read with t.raw() because it holds literal "<name>" placeholders
  // that must not be parsed as ICU/rich-text tags. The importer drops the
  // evidence lines and the trailing provenance sentence.
  const memoryTransferPrompt = t.raw("memoryTransferPrompt") as string;

  async function copyPrompt() {
    // copyToClipboard falls back to execCommand on plain HTTP (on-prem LAN),
    // where navigator.clipboard is unavailable, so the check-state is truthful.
    const ok = await copyToClipboard(memoryTransferPrompt);
    if (!ok) return;
    setPromptCopied(true);
    setTimeout(() => setPromptCopied(false), 1800);
  }

  function onImport(formData: FormData) {
    importAction(formData);
    // The list is server-rendered from listMyMemory; refresh after revalidate.
    router.refresh();
  }

  // ─── Section panes (defined once, placed by the active variant) ──────────

  const profileSection = (
    <Section variant={variant} anchor="profile" title={t("profile")} description={t("profileHint")}>
      <form action={pAction} className="space-y-5">
        <ReadOnlyField label={t("email")} value={email} />
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t("fullName")} name="full_name" defaultValue={u?.full_name} />
          <Field label={t("jobTitle")} name="job_title" defaultValue={u?.job_title} />
          <Field label={t("department")} name="department" defaultValue={u?.department} />
          <Field label={t("phone")} name="phone" defaultValue={u?.phone} type="tel" />
          <Field label={t("location")} name="location" defaultValue={u?.location} />
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
        </div>
        {(profile?.manager_display || profile?.tenure_days != null) && (
          <div className="grid gap-4 rounded-2xl bg-surface-2/60 p-4 sm:grid-cols-2">
            {profile?.manager_display && (
              <ReadOnlyField label={t("manager")} value={profile.manager_display} />
            )}
            {profile?.tenure_days != null && (
              <ReadOnlyField
                label={t("tenure")}
                value={t("tenureDays", { days: profile.tenure_days })}
              />
            )}
          </div>
        )}
        <div className="flex items-center gap-3 pt-1">
          <button type="submit" disabled={pPending} className={ui.btnPrimary}>
            {pPending ? tc("loading") : t("save")}
          </button>
          <FormStatus
            ok={pState.ok}
            okLabel={t("saved")}
            error={pState.error ? t("saveError") : undefined}
          />
        </div>
      </form>
    </Section>
  );

  const securitySection = (
    <Section variant={variant} anchor="security" title={t("security")} description={t("securityHint")}>
      <form action={secAction} className="space-y-5">
        <div className="grid gap-4 sm:grid-cols-3">
          <Field
            label={t("currentPassword")}
            name="current_password"
            type="password"
            autoComplete="current-password"
          />
          <Field
            label={t("newPassword")}
            name="new_password"
            type="password"
            autoComplete="new-password"
            minLength={PASSWORD_MIN_LENGTH}
            maxLength={PASSWORD_MAX_LENGTH}
            hint={tc("passwordHint", { min: PASSWORD_MIN_LENGTH })}
          />
          <Field
            label={t("confirmPassword")}
            name="confirm_password"
            type="password"
            autoComplete="new-password"
            minLength={PASSWORD_MIN_LENGTH}
            maxLength={PASSWORD_MAX_LENGTH}
          />
        </div>
        <div className="flex items-center gap-3 pt-1">
          <button type="submit" disabled={secPending} className={ui.btnPrimary}>
            {secPending ? tc("loading") : t("changePassword")}
          </button>
          <FormStatus
            ok={secState.ok}
            okLabel={t("passwordChanged")}
            error={
              secState.error === "current"
                ? t("currentPasswordWrong")
                : secState.error === "mismatch"
                  ? t("passwordMismatch")
                  : secState.error === "short"
                    ? t("passwordTooShort", { min: PASSWORD_MIN_LENGTH })
                    : secState.error === "policy"
                      ? tc("passwordPolicyError", { min: PASSWORD_MIN_LENGTH, max: PASSWORD_MAX_LENGTH })
                      : secState.error === "generic"
                      ? t("saveError")
                      : undefined
            }
          />
        </div>
      </form>
    </Section>
  );

  // The id="preferences" anchor is linked from the chat profile menu
  // (/account#preferences) — do not rename it.
  const preferencesSection = (
    <Section
      variant={variant}
      anchor="preferences"
      title={t("preferencesTitle")}
      description={t("preferencesHint")}
    >
      <div className="space-y-5">
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <label className={ui.label}>{t("language")}</label>
            <Select
              ariaLabel={t("language")}
              value={locale}
              onValueChange={changeLocale}
              disabled={localePending}
              options={[
                { value: "tr", label: "Türkçe", icon: "translate" },
                { value: "en", label: "English", icon: "translate" },
              ]}
            />
            <p className="text-xs text-ink-muted">{t("languageHint")}</p>
          </div>
        </div>

        <form action={prefAction} className="space-y-5 border-t border-border pt-5">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <label className={ui.label}>{t("answerStyle")}</label>
              <Select
                name="answer_style"
                ariaLabel={t("answerStyle")}
                defaultValue={u?.answer_style ?? "balanced"}
                options={[
                  { value: "balanced", label: t("styleBalanced"), icon: "balance" },
                  { value: "corporate", label: t("styleCorporate"), icon: "corporate_fare" },
                  { value: "short", label: t("styleShort"), icon: "short_text" },
                  { value: "instructive", label: t("styleInstructive"), icon: "school" },
                ]}
              />
            </div>
            {models.allowed_models.length > 0 && (
              <div className="space-y-1.5">
                <label className={ui.label}>{t("preferredModel")}</label>
                <Select
                  name="preferred_chat_model"
                  ariaLabel={t("preferredModel")}
                  defaultValue={u?.preferred_chat_model ?? ""}
                  options={[
                    { value: "", label: t("modelDefault"), icon: "auto_awesome" },
                    ...models.allowed_models.map((m) => ({
                      value: m,
                      // Show the admin's friendly alias; the value stays the raw id.
                      label: models.aliases?.[m] ?? m,
                      icon: "neurology",
                    })),
                  ]}
                />
              </div>
            )}
          </div>
          <p className="text-xs text-ink-muted">{t("answerStyleHint")}</p>
          <div className="flex items-center gap-3 pt-1">
            <button type="submit" disabled={prefPending} className={ui.btnPrimary}>
              {prefPending ? tc("loading") : t("save")}
            </button>
            <FormStatus
              ok={prefState.ok}
              okLabel={t("saved")}
              error={prefState.error ? t("saveError") : undefined}
            />
          </div>
        </form>
      </div>
    </Section>
  );

  const memorySection = (
    <Section variant={variant} anchor="memory" title={t("memory")} description={t("memoryHint")}>
      <div className="space-y-4">
        <MemoryList
          memory={memory}
          cleared={cleared}
          clearing={clearing}
          onClear={clearMemory}
          countLabel={t("memoryCount", { count: memory.length })}
          clearLabel={t("memoryClear")}
          clearedLabel={t("memoryCleared")}
          emptyLabel={t("memoryEmpty")}
          loadingLabel={tc("loading")}
          showMoreLabel={t("memoryShowMore")}
          showLessLabel={t("memoryShowLess")}
        />

        {/* Import disclosure — collapsed by default so it never bloats the page */}
        <div className="rounded-2xl border border-border bg-surface-2/40">
          <button
            type="button"
            onClick={() => setImportOpen((o) => !o)}
            aria-expanded={importOpen}
            aria-controls="memory-import-panel"
            className="flex w-full items-center gap-3 rounded-2xl px-4 py-3 text-left text-sm font-medium text-ink transition-colors hover:bg-surface-2/70"
          >
            <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-brand/10 text-brand">
              <Icon name="move_to_inbox" size={18} />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block">{t("memoryImport")}</span>
              <span className="block text-xs font-normal text-ink-muted">{t("importSubtitle")}</span>
            </span>
            <Icon
              name="expand_more"
              size={20}
              className={`shrink-0 text-ink-muted transition-transform ${importOpen ? "rotate-180" : ""}`}
            />
          </button>

          {importOpen && (
            <div
              id="memory-import-panel"
              className="animate-fade-up space-y-4 border-t border-border px-4 pb-4 pt-4"
            >
              {/* Step 1 — copy the transfer prompt */}
              <div className="space-y-2">
                <div className="flex items-center justify-between gap-3">
                  <span className="inline-flex items-center gap-2 text-sm font-medium text-ink">
                    <StepBadge n={1} />
                    {t("importStep1")}
                  </span>
                  <button
                    type="button"
                    onClick={copyPrompt}
                    className="inline-flex items-center gap-1.5 rounded-full border border-border bg-surface px-3 py-1.5 text-xs font-medium text-ink transition-colors hover:bg-surface-2"
                  >
                    <Icon name={promptCopied ? "check" : "content_copy"} size={16} />
                    {promptCopied ? tc("copied") : tc("copy")}
                  </button>
                </div>
                <pre className="scrollbar-slim max-h-40 overflow-auto whitespace-pre-wrap rounded-xl border border-border bg-surface p-3.5 text-xs leading-relaxed text-ink-muted">
                  {memoryTransferPrompt}
                </pre>
              </div>

              {/* Step 2 — paste the assistant's reply and import */}
              <form action={onImport} className="space-y-2.5">
                <label
                  htmlFor="memory_text"
                  className="inline-flex items-center gap-2 text-sm font-medium text-ink"
                >
                  <StepBadge n={2} />
                  {t("importStep2")}
                </label>
                <textarea
                  id="memory_text"
                  name="memory_text"
                  rows={5}
                  placeholder={t("importPlaceholder")}
                  className="w-full resize-y rounded-xl border border-border bg-surface px-3.5 py-3 text-sm text-ink placeholder:text-ink-muted/60 outline-none transition focus:border-brand focus:ring-4 focus:ring-brand/15"
                />
                <div className="flex flex-wrap items-center gap-3">
                  <button type="submit" disabled={importPending} className={ui.btnPrimary}>
                    {importPending ? tc("loading") : t("importSubmit")}
                  </button>
                  {importState.ok && (
                    <span className="inline-flex items-center gap-1.5 text-sm text-success">
                      <Icon name="check_circle" size={16} fill />
                      {t("importAdded", { added: importState.added ?? 0 })}
                    </span>
                  )}
                  {importState.error === "empty" && (
                    <span className="text-sm text-danger">{t("importEmpty")}</span>
                  )}
                  {importState.error === "tooLong" && (
                    <span className="text-sm text-danger">{t("importTooLong")}</span>
                  )}
                  {importState.error === "generic" && (
                    <span className="text-sm text-danger">{t("importError")}</span>
                  )}
                  {importState.error === "disabled" && (
                    <span className="text-sm text-danger">{t("importDisabled")}</span>
                  )}
                </div>
              </form>
            </div>
          )}
        </div>
      </div>
    </Section>
  );

  const panes: Record<SettingsTab, React.ReactNode> = {
    profile: profileSection,
    security: securitySection,
    preferences: preferencesSection,
    memory: memorySection,
  };

  // Modal: render only the active tab's pane (the rail drives navigation).
  if (variant === "modal") {
    return <>{panes[activeTab ?? "profile"]}</>;
  }

  // Page: the calm editorial stack of every section, divided by hairlines.
  return (
    <div className="space-y-12">
      {SETTINGS_TABS.map((tab) => (
        <div key={tab.id}>{panes[tab.id]}</div>
      ))}
    </div>
  );
}

/** Small numbered step marker for the 2-step import flow. */
function StepBadge({ n }: { n: number }) {
  return (
    <span className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-brand/10 text-[11px] font-semibold text-brand">
      {n}
    </span>
  );
}

/**
 * Compact, capped-height list of remembered facts. A header shows the count and
 * the clear action; the body scrolls so one giant pasted import can't blow up the
 * page. Long facts collapse to two lines with an inline show-more toggle.
 */
function MemoryList({
  memory,
  cleared,
  clearing,
  onClear,
  countLabel,
  clearLabel,
  clearedLabel,
  emptyLabel,
  loadingLabel,
  showMoreLabel,
  showLessLabel,
}: {
  memory: MemoryItem[];
  cleared: boolean;
  clearing: boolean;
  onClear: () => void;
  countLabel: string;
  clearLabel: string;
  clearedLabel: string;
  emptyLabel: string;
  loadingLabel: string;
  showMoreLabel: string;
  showLessLabel: string;
}) {
  if (cleared && memory.length === 0) {
    return (
      <p className="inline-flex items-center gap-1.5 text-sm text-success">
        <Icon name="check_circle" size={16} fill />
        {clearedLabel}
      </p>
    );
  }

  if (memory.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 rounded-2xl border border-dashed border-border py-10 text-center">
        <span className="grid h-10 w-10 place-items-center rounded-full bg-surface-2 text-ink-muted">
          <Icon name="bookmark" size={20} />
        </span>
        <p className="text-sm text-ink-muted">{emptyLabel}</p>
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-2xl border border-border">
      <div className="flex items-center justify-between gap-3 border-b border-border bg-surface-2/50 px-4 py-2.5">
        <span className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
          {countLabel}
        </span>
        <button
          type="button"
          onClick={onClear}
          disabled={clearing}
          className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium text-ink-muted transition-colors hover:bg-surface-2 hover:text-danger disabled:opacity-50"
        >
          <Icon name="delete_sweep" size={16} />
          {clearing ? loadingLabel : clearLabel}
        </button>
      </div>
      <ul className="scrollbar-slim max-h-72 divide-y divide-border overflow-y-auto">
        {memory.map((m, i) => (
          <MemoryRow
            key={i}
            content={m.content}
            showMoreLabel={showMoreLabel}
            showLessLabel={showLessLabel}
          />
        ))}
      </ul>
    </div>
  );
}

/** A single remembered fact. Clamps long text to two lines with a show-more toggle. */
function MemoryRow({
  content,
  showMoreLabel,
  showLessLabel,
}: {
  content: string;
  showMoreLabel: string;
  showLessLabel: string;
}) {
  const [expanded, setExpanded] = useState(false);
  // Only offer a toggle for facts long enough to actually clamp (~2 lines).
  const isLong = content.length > 140;

  return (
    <li className="flex items-start gap-2.5 px-4 py-2.5 text-sm">
      <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-brand/60" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className={`text-ink ${expanded ? "" : "line-clamp-2"}`}>{content}</p>
        {isLong && (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="mt-0.5 text-xs font-medium text-brand transition-colors hover:text-brand-strong"
          >
            {expanded ? showLessLabel : showMoreLabel}
          </button>
        )}
      </div>
    </li>
  );
}
