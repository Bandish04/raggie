// SPDX-License-Identifier: Apache-2.0

"use client";

// The Scheduled Tasks modal, opened from the sidebar "Zamanlanmış görevler"
// entry. Two views inside one calm dialog:
//   - LIST: the user's tasks (name, human schedule, workspace, enabled toggle,
//     last run + status, edit/delete) with a calm empty state.
//   - FORM: create (conversational-first — describe it, parse via /api/schedule/
//     parse, then confirm/edit) or edit (the same editable form). Manual entry is
//     always available (skip the NL step). Mutations go through the task server
//     actions, then router.refresh() so chat/page refetches the list.
// Reuses ui/Modal, ui/Select, and the chat Icon; matches the personal-skill
// modal's field density and the "Sakin & Ferah" design language.

import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { Modal } from "@/components/ui/modal";
import Select from "@/components/ui/select";
import {
  createScheduledTaskAction,
  deleteScheduledTaskAction,
  updateScheduledTaskAction,
} from "@/app/chat/task-actions";
import type {
  AnswerStyle,
  ModelsConfig,
  ScheduledTask,
  WorkspaceSummary,
} from "@/lib/api";
import { parseEdgeError } from "@/lib/edge-errors";

function Icon({ name, className = "", fill = false }: { name: string; className?: string; fill?: boolean }) {
  return (
    <span aria-hidden className={`material-symbols-outlined ${fill ? "fill" : ""} ${className}`}>
      {name}
    </span>
  );
}

// Answer-style values the backend accepts (the select's non-"" options).
const TASK_STYLE_VALUES: AnswerStyle[] = ["corporate", "short", "instructive", "balanced"];

// Format an ISO timestamp as a short, locale-aware date+time for "last run".
function fmtDateTime(iso: string | null, locale: string): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleString(locale, {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// What the NL parse returns (same-origin /api/schedule/parse). On failure the
// edge returns its error envelope { error, code, message } instead.
type ParseResult = { cron?: string; prompt?: string; name?: string; summary?: string; error?: string };

/* ───────── Schedule builder ─────────
   A human-friendly frequency → cron generator so users never have to write cron.
   `cron` (the form field) stays the single source of truth that gets submitted;
   the builder both generates it and reverse-maps an incoming cron back into the
   controls (NL-parse result or an edited task). "Custom" reveals the raw field. */

type Frequency = "daily" | "weekdays" | "weekly" | "monthly" | "hourly" | "custom";

// Derived builder controls. `time` is "HH:MM"; `dow` is the cron weekday
// (0=Sun…6=Sat) for "weekly"; `dom` is the day-of-month (1…28) for "monthly".
type ScheduleParts = { freq: Frequency; time: string; dow: number; dom: number };

const DEFAULT_PARTS: ScheduleParts = { freq: "daily", time: "09:00", dow: 1, dom: 1 };

// Cron weekday order, Monday-first for the day-of-week select. Each entry's
// `dow` is the standard cron value (Sunday = 0).
const WEEKDAYS: { dow: number; key: string }[] = [
  { dow: 1, key: "taskDayMon" },
  { dow: 2, key: "taskDayTue" },
  { dow: 3, key: "taskDayWed" },
  { dow: 4, key: "taskDayThu" },
  { dow: 5, key: "taskDayFri" },
  { dow: 6, key: "taskDaySat" },
  { dow: 0, key: "taskDaySun" },
];

// Curated IANA timezones the picker offers (mirrors the account-settings list).
// The form also surfaces the device's detected zone and the task's own zone, so
// a value outside this list still appears — this is just the convenient shortlist.
const TIMEZONES = [
  "Europe/Istanbul",
  "Europe/London",
  "Europe/Berlin",
  "America/New_York",
  "America/Los_Angeles",
  "Asia/Dubai",
  "UTC",
];

const pad2 = (n: number) => String(n).padStart(2, "0");

// Build a standard 5-field cron from the builder controls. Always 5 fields.
function partsToCron(p: ScheduleParts): string {
  const [hh, mm] = p.time.split(":");
  const H = String(Number(hh) || 0);
  const M = String(Number(mm) || 0);
  switch (p.freq) {
    case "daily":
      return `${M} ${H} * * *`;
    case "weekdays":
      return `${M} ${H} * * 1-5`;
    case "weekly":
      return `${M} ${H} * * ${p.dow}`;
    case "monthly":
      return `${M} ${H} ${p.dom} * *`;
    case "hourly":
      return `0 * * * *`;
    default:
      return ""; // custom: the raw field drives `cron`
  }
}

const inRange = (n: number, lo: number, hi: number) => Number.isInteger(n) && n >= lo && n <= hi;

// Reverse-map a cron string into builder controls. Recognises the shapes the
// builder emits (daily / weekdays / weekly / monthly / hourly); anything else
// falls back to "custom" so the raw cron is shown and edited directly.
function cronToParts(cron: string): ScheduleParts {
  const f = cron.trim().split(/\s+/);
  if (f.length !== 5) return { ...DEFAULT_PARTS, freq: "custom" };
  const [min, hr, dom, mon, dow] = f;
  const minN = Number(min);
  const hrN = Number(hr);

  // Every hour: "0 * * * *" (and the looser "MM * * * *" the spec allows).
  if (hr === "*" && dom === "*" && mon === "*" && dow === "*" && inRange(minN, 0, 59)) {
    return { ...DEFAULT_PARTS, freq: "hourly" };
  }

  // The remaining shapes all need a concrete minute + hour.
  if (!inRange(minN, 0, 59) || !inRange(hrN, 0, 23) || mon !== "*") {
    return { ...DEFAULT_PARTS, freq: "custom" };
  }
  const time = `${pad2(hrN)}:${pad2(minN)}`;

  // Monthly: "MM HH N * *" (numeric day-of-month, weekday wildcard).
  if (dow === "*" && dom !== "*") {
    const domN = Number(dom);
    if (inRange(domN, 1, 28)) return { freq: "monthly", time, dow: DEFAULT_PARTS.dow, dom: domN };
    return { ...DEFAULT_PARTS, freq: "custom" };
  }

  // The day-of-month must be wildcard for the weekday-based shapes.
  if (dom !== "*") return { ...DEFAULT_PARTS, freq: "custom" };

  // Daily: "MM HH * * *".
  if (dow === "*") return { freq: "daily", time, dow: DEFAULT_PARTS.dow, dom: DEFAULT_PARTS.dom };

  // Weekdays: "MM HH * * 1-5".
  if (dow === "1-5") return { freq: "weekdays", time, dow: DEFAULT_PARTS.dow, dom: DEFAULT_PARTS.dom };

  // Weekly: "MM HH * * D" with a single weekday 0–6.
  const dowN = Number(dow);
  if (inRange(dowN, 0, 6)) return { freq: "weekly", time, dow: dowN, dom: DEFAULT_PARTS.dom };

  return { ...DEFAULT_PARTS, freq: "custom" };
}

// The editable form's local state — a superset of ScheduledTaskInput plus the
// human-readable `summary` we keep only for display (never sent).
type FormState = {
  name: string;
  prompt: string;
  cron: string;
  summary: string;
  workspaceId: string;
  webSearch: boolean;
  deepSearch: boolean;
  model: string;
  answerStyle: string;
  enabled: boolean;
};

function emptyForm(workspaceId: string): FormState {
  return {
    name: "",
    prompt: "",
    // Seed a sensible default schedule (daily 09:00) so the builder and the
    // submitted cron agree from the first render; the NL parse overrides it.
    cron: partsToCron(DEFAULT_PARTS),
    summary: "",
    workspaceId,
    webSearch: false,
    deepSearch: false,
    model: "",
    answerStyle: "",
    enabled: true,
  };
}

function formFromTask(task: ScheduledTask): FormState {
  return {
    name: task.name,
    prompt: task.prompt,
    cron: task.cron,
    summary: "",
    workspaceId: task.workspace_id,
    webSearch: task.web_search,
    deepSearch: task.deep_search,
    model: task.model ?? "",
    answerStyle: task.answer_style ?? "",
    enabled: task.enabled,
  };
}

/* A calm labelled toggle row (web search / deep research / enabled). Mirrors the
   composer tool-row look: icon + label on the left, a small switch on the right. */
function ToggleRow({
  icon,
  label,
  checked,
  onChange,
}: {
  icon: string;
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className="flex w-full items-center gap-2.5 rounded-xl border border-border bg-surface px-3 py-2.5 text-left text-sm outline-none transition hover:bg-surface-2 focus-visible:border-brand"
    >
      <Icon name={icon} className={`text-lg ${checked ? "text-brand-strong" : "text-ink-muted"}`} fill={checked} />
      <span className="min-w-0 flex-1 truncate text-ink">{label}</span>
      <span
        className={`relative h-5 w-9 shrink-0 rounded-full transition-colors ${
          checked ? "bg-brand" : "bg-surface-3"
        }`}
      >
        <span
          className={`absolute top-0.5 h-4 w-4 rounded-full bg-surface shadow-soft transition-transform ${
            checked ? "translate-x-[18px]" : "translate-x-0.5"
          }`}
        />
      </span>
    </button>
  );
}

/* The create/edit form. On create it leads with a conversational one-liner that
   POSTs to /api/schedule/parse and fills the fields; the user can also skip it and
   fill manually. Submitting calls the create/update action; the parent handles the
   router.refresh() + closing on success. */
function TaskForm({
  editing,
  workspaces,
  models,
  timezone,
  onCancel,
  onSaved,
}: {
  editing: ScheduledTask | null;
  workspaces: WorkspaceSummary[];
  models: ModelsConfig;
  timezone: string;
  onCancel: () => void;
  onSaved: () => void;
}) {
  const t = useTranslations("chat");
  const tc = useTranslations("common");
  const [saving, startSave] = useTransition();

  const [form, setForm] = useState<FormState>(
    editing ? formFromTask(editing) : emptyForm(workspaces[0]?.id ?? ""),
  );
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) =>
    setForm((f) => ({ ...f, [k]: v }));

  // Conversational create: the NL describe line + its loading/error state. Only
  // shown on create (edit jumps straight to the populated form).
  const [describe, setDescribe] = useState("");
  const [parsing, setParsing] = useState(false);
  // Failure text for the NL parse: a translated edge error code, else the
  // generic "couldn't understand" hint (also used for parse_failed).
  const [parseError, setParseError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState(false);

  // Schedule builder: human-friendly controls that generate `form.cron`. The
  // controls are reverse-mapped from the initial cron (edit or NL-parse result);
  // thereafter the builder drives the cron, and a fresh NL parse re-derives them.
  const [parts, setParts] = useState<ScheduleParts>(() =>
    form.cron.trim() ? cronToParts(form.cron) : DEFAULT_PARTS,
  );

  // Timezone the task runs in. Editing keeps the task's stored zone; creating
  // defaults to the user's selected location (profile `timezone` prop). The
  // device's own zone is detected after mount (SSR-safe) and offered first so
  // "my local time" is one click away. The scheduler honours this per task, so
  // a "09:00" task fires at 09:00 in *this* zone — never the server's clock.
  const [tz, setTz] = useState<string>(editing?.timezone ?? timezone);
  const [deviceTz] = useState<string | null>(() => {
    try {
      return Intl.DateTimeFormat().resolvedOptions().timeZone || null;
    } catch {
      return null;
    }
  });
  // Build the option list: device zone first (labelled), then the current zone,
  // then the shortlist — de-duplicated, so the selected value always appears.
  const timezoneOptions = Array.from(
    new Set([...(deviceTz ? [deviceTz] : []), tz, ...TIMEZONES]),
  ).map((z) => ({
    value: z,
    label: z === deviceTz ? `${z} ${t("taskTimezoneDevice")}` : z,
    icon: "schedule",
  }));

  // Apply a builder control change: update the parts AND keep `form.cron` in
  // sync (for the non-custom frequencies, which fully derive the cron). In
  // "custom" mode the raw field is the source of truth, so the cron is left as-is.
  function setPart<K extends keyof ScheduleParts>(k: K, v: ScheduleParts[K]) {
    const next = { ...parts, [k]: v };
    setParts(next);
    if (next.freq !== "custom") {
      setForm((f) => ({ ...f, cron: partsToCron(next), summary: "" }));
    }
  }

  async function parse() {
    const text = describe.trim();
    if (!text || parsing) return;
    setParsing(true);
    setParseError(null);
    try {
      const res = await fetch("/api/schedule/parse", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, timezone: tz }),
      });
      const data = (await res.json()) as ParseResult;
      if (res.ok && data.cron) {
        const cron = data.cron;
        setForm((f) => ({
          ...f,
          name: data.name?.trim() || f.name,
          prompt: data.prompt?.trim() || f.prompt,
          cron,
          summary: data.summary?.trim() ?? "",
        }));
        // Reverse-map the parsed cron into the builder controls so they reflect it.
        setParts(cronToParts(cron));
      } else {
        const { code } = parseEdgeError(data);
        setParseError(code && code !== "parse_failed" ? t(`edgeErrors.${code}`) : t("taskParseError"));
      }
    } catch {
      setParseError(t("taskParseError"));
    } finally {
      setParsing(false);
    }
  }

  const modelOptions = [
    { value: "", label: t("taskModelDefault"), icon: "auto_awesome" },
    ...(models.allowed_models ?? []).map((m) => ({
      value: m,
      label: models.aliases?.[m] ?? m,
      icon: "neurology",
    })),
  ];
  const styleOptions = [
    { value: "", label: t("taskStyleDefault") },
    { value: "corporate", label: t("taskStyleCorporate") },
    { value: "short", label: t("taskStyleShort") },
    { value: "instructive", label: t("taskStyleInstructive") },
    { value: "balanced", label: t("taskStyleBalanced") },
  ];
  const workspaceOptions = workspaces.map((w) => ({
    value: w.id,
    label: w.name,
    icon: "workspaces",
  }));

  // Schedule-builder option lists.
  const frequencyOptions = [
    { value: "daily", label: t("taskFreqDaily"), icon: "today" },
    { value: "weekdays", label: t("taskFreqWeekdays"), icon: "date_range" },
    { value: "weekly", label: t("taskFreqWeekly"), icon: "event_repeat" },
    { value: "monthly", label: t("taskFreqMonthly"), icon: "calendar_month" },
    { value: "hourly", label: t("taskFreqHourly"), icon: "hourglass_empty" },
    { value: "custom", label: t("taskFreqCustom"), icon: "tune" },
  ];
  const weekdayOptions = WEEKDAYS.map((d) => ({ value: String(d.dow), label: t(d.key) }));
  const monthDayOptions = Array.from({ length: 28 }, (_, i) => ({
    value: String(i + 1),
    label: String(i + 1),
  }));

  // The builder's own derived summary (always correct for the current controls).
  // For "custom" we fall back to the NL-parse summary if one is present.
  const builderSummary = (() => {
    switch (parts.freq) {
      case "daily":
        return t("taskSummaryDaily", { time: parts.time });
      case "weekdays":
        return t("taskSummaryWeekdays", { time: parts.time });
      case "weekly":
        return t("taskSummaryWeekly", {
          day: t(WEEKDAYS.find((d) => d.dow === parts.dow)?.key ?? "taskDayMon"),
          time: parts.time,
        });
      case "monthly":
        return t("taskSummaryMonthly", { day: parts.dom, time: parts.time });
      case "hourly":
        return t("taskSummaryHourly");
      default:
        return form.summary || "";
    }
  })();

  // A valid cron is always 5 whitespace-separated fields (the builder guarantees
  // this for every non-custom frequency; this also gates a malformed raw entry).
  const cronIsValid = form.cron.trim().split(/\s+/).filter(Boolean).length === 5;
  const canSave =
    form.name.trim().length > 0 &&
    form.prompt.trim().length > 0 &&
    cronIsValid &&
    form.workspaceId.length > 0;

  function submit() {
    if (!canSave || saving) return;
    setSaveError(false);
    const body = {
      name: form.name.trim(),
      workspace_id: form.workspaceId,
      prompt: form.prompt.trim(),
      cron: form.cron.trim(),
      timezone: tz,
      web_search: form.webSearch,
      deep_search: form.deepSearch,
      model: form.model || null,
      answer_style: TASK_STYLE_VALUES.includes(form.answerStyle as AnswerStyle)
        ? (form.answerStyle as AnswerStyle)
        : null,
      enabled: form.enabled,
    };
    startSave(async () => {
      const res = editing
        ? await updateScheduledTaskAction(editing.id, body)
        : await createScheduledTaskAction(body);
      if (res.ok) onSaved();
      else setSaveError(true);
    });
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
      className="space-y-4"
    >
      {/* Conversational create (create only): describe it → parse → fill fields. */}
      {!editing && (
        <div className="rounded-xl border border-border bg-surface-2/50 p-2.5">
          <label htmlFor="task-describe" className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-ink-muted">
            <Icon name="auto_awesome" className="text-sm text-brand" />
            {t("taskDescribe")}
          </label>
          <div className="flex items-center gap-2">
            <input
              id="task-describe"
              value={describe}
              onChange={(e) => setDescribe(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  void parse();
                }
              }}
              disabled={parsing}
              placeholder={t("taskDescribePlaceholder")}
              className="min-w-0 flex-1 rounded-lg border border-border bg-surface px-3 py-2 text-sm text-ink outline-none transition placeholder:text-ink-muted/60 focus:border-brand disabled:opacity-60"
            />
            <button
              type="button"
              onClick={() => void parse()}
              disabled={parsing || !describe.trim()}
              className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-brand/10 px-3 py-2 text-xs font-medium text-brand-strong outline-none transition hover:bg-brand/20 focus-visible:ring-2 focus-visible:ring-brand/30 disabled:opacity-50"
            >
              <Icon
                name={parsing ? "progress_activity" : "auto_awesome"}
                className={`text-base ${parsing ? "animate-spin" : ""}`}
              />
              {parsing ? t("taskGenerating") : t("taskGenerate")}
            </button>
          </div>
          {parseError && (
            <p className="mt-1.5 text-xs text-danger" role="alert">
              {parseError}
            </p>
          )}
        </div>
      )}

      {/* Name + workspace */}
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-1.5">
          <label htmlFor="task-name" className="text-sm font-medium text-ink">
            {t("taskName")}
          </label>
          <input
            id="task-name"
            value={form.name}
            onChange={(e) => set("name", e.target.value)}
            required
            className="h-10 w-full rounded-xl border border-border bg-surface px-3 text-sm text-ink outline-none transition placeholder:text-ink-muted/60 focus:border-brand"
            placeholder={t("taskNamePlaceholder")}
          />
        </div>
        <div className="space-y-1.5">
          <label className="text-sm font-medium text-ink">{t("taskWorkspace")}</label>
          <Select
            options={workspaceOptions}
            value={form.workspaceId}
            onValueChange={(v) => set("workspaceId", v)}
            ariaLabel={t("taskWorkspace")}
          />
        </div>
      </div>

      {/* Prompt */}
      <div className="space-y-1.5">
        <label htmlFor="task-prompt" className="text-sm font-medium text-ink">
          {t("taskPrompt")}
        </label>
        <textarea
          id="task-prompt"
          value={form.prompt}
          onChange={(e) => set("prompt", e.target.value)}
          required
          rows={3}
          className="w-full resize-y rounded-xl border border-border bg-surface px-3 py-2.5 text-sm leading-relaxed text-ink outline-none transition placeholder:text-ink-muted/60 focus:border-brand"
          placeholder={t("taskPromptPlaceholder")}
        />
      </div>

      {/* Schedule: a human-friendly builder (frequency + time/day) that generates
          the cron, with an "advanced (cron)" raw field for the Custom frequency. */}
      <div className="space-y-3">
        {/* Frequency + the conditional time / day-of-week / day-of-month control. */}
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <label className="text-sm font-medium text-ink">{t("taskFrequency")}</label>
            <Select
              options={frequencyOptions}
              value={parts.freq}
              onValueChange={(v) => setPart("freq", v as Frequency)}
              ariaLabel={t("taskFrequency")}
            />
          </div>

          {/* Time — shown for the time-of-day frequencies. */}
          {(parts.freq === "daily" ||
            parts.freq === "weekdays" ||
            parts.freq === "weekly" ||
            parts.freq === "monthly") && (
            <div className="space-y-1.5">
              <label htmlFor="task-time" className="text-sm font-medium text-ink">
                {t("taskTime")}
              </label>
              <input
                id="task-time"
                type="time"
                value={parts.time}
                onChange={(e) => setPart("time", e.target.value || "09:00")}
                className="h-10 w-full rounded-xl border border-border bg-surface px-3 text-sm text-ink outline-none transition focus:border-brand"
              />
            </div>
          )}

          {/* Day of week — weekly only. */}
          {parts.freq === "weekly" && (
            <div className="space-y-1.5">
              <label className="text-sm font-medium text-ink">{t("taskDayOfWeek")}</label>
              <Select
                options={weekdayOptions}
                value={String(parts.dow)}
                onValueChange={(v) => setPart("dow", Number(v))}
                ariaLabel={t("taskDayOfWeek")}
              />
            </div>
          )}

          {/* Day of month — monthly only. */}
          {parts.freq === "monthly" && (
            <div className="space-y-1.5">
              <label className="text-sm font-medium text-ink">{t("taskDayOfMonth")}</label>
              <Select
                options={monthDayOptions}
                value={String(parts.dom)}
                onValueChange={(v) => setPart("dom", Number(v))}
                ariaLabel={t("taskDayOfMonth")}
              />
            </div>
          )}
        </div>

        {/* Timezone — the task runs in this zone (defaults to the user's selected
            location; the device's own zone is offered first). Always shown so the
            schedule is never ambiguous about which clock it follows. */}
        <div className="space-y-1.5">
          <label className="text-sm font-medium text-ink">{t("taskTimezone")}</label>
          <Select
            options={timezoneOptions}
            value={tz}
            onValueChange={setTz}
            ariaLabel={t("taskTimezone")}
          />
          <p className="text-xs text-ink-muted">{t("taskTimezoneHelp")}</p>
        </div>

        {/* Advanced raw-cron field — only for the Custom frequency. Uses the same
            label + full-width input pattern as the other fields so it aligns. */}
        {parts.freq === "custom" && (
          <div className="space-y-1.5">
            <label htmlFor="task-cron" className="text-sm font-medium text-ink">
              {t("taskCronAdvancedField")}
            </label>
            <input
              id="task-cron"
              value={form.cron}
              onChange={(e) => set("cron", e.target.value)}
              required
              autoCapitalize="off"
              autoCorrect="off"
              spellCheck={false}
              className="h-10 w-full rounded-xl border border-border bg-surface px-3 font-mono text-sm text-ink outline-none transition placeholder:text-ink-muted/60 focus:border-brand"
              placeholder="0 9 * * *"
            />
            <p className="text-xs text-ink-muted">{t("taskCronHelp")}</p>
          </div>
        )}

        {/* Human-readable summary + timezone — a calm, always-true derivation. */}
        {builderSummary && (
          <p className="flex items-center gap-1.5 rounded-xl bg-brand/5 px-3 py-2 text-sm text-ink">
            <Icon name="schedule" className="text-base text-brand" />
            <span className="min-w-0 flex-1 truncate">{builderSummary}</span>
            <span className="shrink-0 text-xs text-ink-muted">{tz}</span>
          </p>
        )}
      </div>

      {/* Tools: web search + deep research toggles. */}
      <div className="grid gap-2.5 sm:grid-cols-2">
        <ToggleRow
          icon="language"
          label={t("taskWebSearch")}
          checked={form.webSearch}
          onChange={(v) => set("webSearch", v)}
        />
        <ToggleRow
          icon="travel_explore"
          label={t("taskDeepSearch")}
          checked={form.deepSearch}
          onChange={(v) => set("deepSearch", v)}
        />
      </div>

      {/* Model + answer style (model only when the deployment exposes a choice). */}
      <div className="grid gap-4 sm:grid-cols-2">
        {(models.allowed_models?.length ?? 0) > 0 && (
          <div className="space-y-1.5">
            <label className="text-sm font-medium text-ink">{t("taskModel")}</label>
            <Select
              options={modelOptions}
              value={form.model}
              onValueChange={(v) => set("model", v)}
              ariaLabel={t("taskModel")}
            />
          </div>
        )}
        <div className="space-y-1.5">
          <label className="text-sm font-medium text-ink">{t("taskAnswerStyle")}</label>
          <Select
            options={styleOptions}
            value={form.answerStyle}
            onValueChange={(v) => set("answerStyle", v)}
            ariaLabel={t("taskAnswerStyle")}
          />
        </div>
      </div>

      {/* Enabled */}
      <ToggleRow
        icon="alarm"
        label={t("taskEnabled")}
        checked={form.enabled}
        onChange={(v) => set("enabled", v)}
      />

      {saveError && (
        <p className="rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger" role="alert">
          {t("taskSaveError")}
        </p>
      )}

      <div className="flex items-center justify-end gap-3 pt-1">
        <button
          type="button"
          onClick={onCancel}
          className="rounded-xl px-4 py-2 text-sm font-medium text-ink-muted transition hover:bg-surface-2 hover:text-ink"
        >
          {tc("cancel")}
        </button>
        <button
          type="submit"
          disabled={!canSave || saving}
          className="rounded-xl bg-brand px-4 py-2 text-sm font-medium text-white transition hover:bg-brand/90 disabled:opacity-40"
        >
          {saving ? tc("loading") : editing ? t("taskSave") : t("taskCreate")}
        </button>
      </div>
    </form>
  );
}

/* A single task row in the list: name, human schedule (summary derived from cron
   + timezone), the workspace name, an enabled toggle, last-run + status, and
   edit/delete. Calm and dense, matching the skills menu rows. */
function TaskRow({
  task,
  workspaceName,
  busy,
  onToggle,
  onEdit,
  onDelete,
}: {
  task: ScheduledTask;
  workspaceName: string;
  busy: boolean;
  onToggle: (next: boolean) => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const t = useTranslations("chat");
  const locale = useLocale();
  const lastRun = fmtDateTime(task.last_run_at, locale);

  return (
    <li className="rounded-2xl border border-border bg-surface p-3">
      <div className="flex items-start gap-3">
        <span
          className={`mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg ${
            task.enabled ? "bg-brand/10 text-brand" : "bg-surface-2 text-ink-muted"
          }`}
        >
          <Icon name="schedule" className="text-base" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate text-sm font-medium text-ink">{task.name}</span>
            {!task.enabled && (
              <span className="shrink-0 rounded-full bg-surface-2 px-1.5 py-px text-[10px] font-medium text-ink-muted">
                {t("taskDisable")}
              </span>
            )}
          </div>
          {/* Schedule: cron + timezone (a compact, always-true derivation). */}
          <p className="mt-0.5 flex items-center gap-1.5 text-xs text-ink-muted">
            <span className="font-mono">{task.cron}</span>
            <span className="opacity-50">·</span>
            <span className="truncate">{task.timezone}</span>
          </p>
          {/* Workspace + last run/status — a quiet meta line. */}
          <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-ink-muted">
            <span className="inline-flex items-center gap-1">
              <Icon name="workspaces" className="text-[13px]" />
              {workspaceName}
            </span>
            <span className="opacity-50">·</span>
            {lastRun ? (
              <span className="inline-flex items-center gap-1">
                {task.last_status === "ok" && <Icon name="check_circle" className="text-[13px] text-success" />}
                {task.last_status === "error" && <Icon name="error" className="text-[13px] text-danger" />}
                {t("taskLastRun")}: {lastRun}
              </span>
            ) : (
              <span>{t("taskNeverRan")}</span>
            )}
          </p>
        </div>
        {/* Controls: enabled toggle + edit + delete. */}
        <div className="flex shrink-0 items-center gap-0.5">
          <button
            type="button"
            role="switch"
            aria-checked={task.enabled}
            aria-label={task.enabled ? t("taskDisable") : t("taskEnable")}
            title={task.enabled ? t("taskDisable") : t("taskEnable")}
            disabled={busy}
            onClick={() => onToggle(!task.enabled)}
            className="mr-1 disabled:opacity-50"
          >
            <span
              className={`relative block h-5 w-9 rounded-full transition-colors ${
                task.enabled ? "bg-brand" : "bg-surface-3"
              }`}
            >
              <span
                className={`absolute top-0.5 h-4 w-4 rounded-full bg-surface shadow-soft transition-transform ${
                  task.enabled ? "translate-x-[18px]" : "translate-x-0.5"
                }`}
              />
            </span>
          </button>
          <button
            type="button"
            onClick={onEdit}
            aria-label={t("taskEdit")}
            title={t("taskEdit")}
            className="grid h-7 w-7 place-items-center rounded-lg text-ink-muted transition hover:bg-surface-2 hover:text-ink"
          >
            <Icon name="edit" className="text-sm" />
          </button>
          <button
            type="button"
            onClick={onDelete}
            aria-label={t("taskDelete")}
            title={t("taskDelete")}
            className="grid h-7 w-7 place-items-center rounded-lg text-ink-muted transition hover:bg-surface-2 hover:text-danger"
          >
            <Icon name="delete" className="text-sm" />
          </button>
        </div>
      </div>
    </li>
  );
}

/* The Scheduled Tasks modal. Holds the list ⇄ form switch; mutations go through
   the server actions, then router.refresh() so chat/page refetches the list. */
export default function ScheduledTasksModal({
  open,
  onClose,
  tasks,
  workspaces,
  models,
  timezone,
}: {
  open: boolean;
  onClose: () => void;
  tasks: ScheduledTask[];
  workspaces: WorkspaceSummary[];
  models: ModelsConfig;
  timezone: string;
}) {
  const t = useTranslations("chat");
  const router = useRouter();
  const [, startMutate] = useTransition();
  // View: the list, or the form (create = null, edit = a task).
  const [view, setView] = useState<{ form: false } | { form: true; editing: ScheduledTask | null }>({
    form: false,
  });
  // The task whose enable/disable toggle is in flight (disables its switch).
  const [togglingId, setTogglingId] = useState<string | null>(null);
  // Inline delete confirm: the row awaiting confirmation.
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  const wsName = (id: string) => workspaces.find((w) => w.id === id)?.name ?? id;
  const noWorkspaces = workspaces.length === 0;

  function backToList() {
    setView({ form: false });
  }
  function onSaved() {
    setView({ form: false });
    router.refresh();
  }

  function toggleTask(task: ScheduledTask, next: boolean) {
    setTogglingId(task.id);
    startMutate(async () => {
      await updateScheduledTaskAction(task.id, { enabled: next });
      setTogglingId(null);
      router.refresh();
    });
  }

  function removeTask(task: ScheduledTask) {
    startMutate(async () => {
      await deleteScheduledTaskAction(task.id);
      setConfirmDeleteId(null);
      router.refresh();
    });
  }

  const inForm = view.form;
  const title = inForm ? (view.editing ? t("taskEdit") : t("taskNew")) : t("tasksTitle");

  return (
    <Modal open={open} onClose={onClose} size="lg" title={title}>
      {inForm ? (
        <TaskForm
          editing={view.editing}
          workspaces={workspaces}
          models={models}
          timezone={timezone}
          onCancel={backToList}
          onSaved={onSaved}
        />
      ) : (
        <div className="space-y-4">
          <p className="text-sm text-ink-muted">{t("tasksSubtitle")}</p>

          {tasks.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-border bg-surface px-6 py-12 text-center">
              <span className="grid h-12 w-12 place-items-center rounded-2xl bg-surface-2 text-ink-muted">
                <Icon name="schedule" className="text-2xl" />
              </span>
              <div>
                <p className="font-display text-base font-semibold text-ink">{t("taskEmpty")}</p>
                <p className="mt-1 max-w-sm text-sm text-ink-muted">{t("taskEmptyHint")}</p>
              </div>
            </div>
          ) : (
            <ul className="scrollbar-slim max-h-[50vh] space-y-2 overflow-y-auto">
              {tasks.map((task) =>
                confirmDeleteId === task.id ? (
                  <li
                    key={task.id}
                    className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-danger/30 bg-danger/5 p-3"
                  >
                    <span className="flex min-w-0 items-center gap-2 text-sm text-ink">
                      <Icon name="delete" className="shrink-0 text-base text-danger" />
                      <span className="min-w-0">{t("taskDeleteConfirm", { name: task.name })}</span>
                    </span>
                    <span className="flex shrink-0 items-center gap-2">
                      <button
                        type="button"
                        onClick={() => setConfirmDeleteId(null)}
                        className="rounded-lg px-3 py-1.5 text-xs font-medium text-ink-muted transition hover:bg-surface-2 hover:text-ink"
                      >
                        {t("deleteChatCancel")}
                      </button>
                      <button
                        type="button"
                        onClick={() => removeTask(task)}
                        className="inline-flex items-center gap-1.5 rounded-lg bg-danger px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-danger/90"
                      >
                        <Icon name="delete" className="text-sm" />
                        {t("taskDelete")}
                      </button>
                    </span>
                  </li>
                ) : (
                  <TaskRow
                    key={task.id}
                    task={task}
                    workspaceName={wsName(task.workspace_id)}
                    busy={togglingId === task.id}
                    onToggle={(next) => toggleTask(task, next)}
                    onEdit={() => setView({ form: true, editing: task })}
                    onDelete={() => setConfirmDeleteId(task.id)}
                  />
                ),
              )}
            </ul>
          )}

          {/* New task — disabled (with a hint) when there's no workspace to run in. */}
          {noWorkspaces ? (
            <p className="rounded-xl bg-surface-2 px-3 py-2 text-xs text-ink-muted">{t("taskNoWorkspace")}</p>
          ) : (
            <button
              type="button"
              onClick={() => setView({ form: true, editing: null })}
              className="flex w-full items-center justify-center gap-2 rounded-2xl border border-dashed border-border px-4 py-2.5 text-sm font-medium text-ink-muted transition hover:border-brand/40 hover:bg-surface-2 hover:text-ink"
            >
              <Icon name="add" className="text-base" />
              {t("taskNew")}
            </button>
          )}
        </div>
      )}
    </Modal>
  );
}
