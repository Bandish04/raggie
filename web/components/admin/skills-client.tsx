// SPDX-License-Identifier: Apache-2.0

"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useMemo, useState, useTransition } from "react";

import {
  createSkillAction,
  deleteSkillAction,
  updateSkillAction,
} from "@/app/admin/skills/actions";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Icon } from "@/components/ui/icon";
import IconPicker from "@/components/ui/icon-picker";
import { Modal } from "@/components/ui/modal";
import Select from "@/components/ui/select";
import SkillGenerate from "@/components/ui/skill-generate";
import type { AnswerStyle, ModelsConfig, Skill, SkillInput } from "@/lib/api";
import { ui } from "@/lib/ui";

// Constrain free text to the slug grammar the backend accepts (a-z, 0-9, -;
// <=32). Applied live as the admin types so the helper text never lies.
function slugify(raw: string): string {
  return raw
    .toLowerCase()
    .replace(/[^a-z0-9-]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-+/, "")
    .slice(0, 32);
}

// The "no override" sentinel for the optional model / answer-style selects. The
// real values never collide with it, and it maps back to null on submit.
const NONE = "";

const STYLE_VALUES: AnswerStyle[] = ["corporate", "short", "instructive", "balanced"];
const TOOL_VALUES = ["web_search", "deep_research", "mcp"] as const;

// ───────────────────────── Create / edit modal ─────────────────────────
function SkillModal({
  open,
  onClose,
  editing,
  models,
}: {
  open: boolean;
  onClose: () => void;
  editing: Skill | null;
  models: ModelsConfig;
}) {
  const t = useTranslations("admin");
  const tc = useTranslations("common");
  const router = useRouter();
  const [saving, startSave] = useTransition();

  const [name, setName] = useState(editing?.name ?? "");
  // Once a slug exists we keep it stable on edit; for a new skill it tracks the
  // name until the admin types into the slug field themselves (then it sticks).
  const [slug, setSlug] = useState(editing?.slug ?? "");
  const [slugDirty, setSlugDirty] = useState(!!editing);
  const [description, setDescription] = useState(editing?.description ?? "");
  const [icon, setIcon] = useState(editing?.icon ?? "");
  const [instructions, setInstructions] = useState(editing?.instructions ?? "");
  const [model, setModel] = useState(editing?.model ?? NONE);
  const [answerStyle, setAnswerStyle] = useState<string>(editing?.answer_style ?? NONE);
  const [allowedTools, setAllowedTools] = useState<string[]>(editing?.allowed_tools ?? []);
  const [enabled, setEnabled] = useState(editing?.enabled ?? true);

  const [duplicate, setDuplicate] = useState(false);
  const [error, setError] = useState(false);

  function onNameChange(v: string) {
    setName(v);
    if (!slugDirty) setSlug(slugify(v));
  }
  function onSlugChange(v: string) {
    setSlugDirty(true);
    setSlug(slugify(v));
  }

  const allowed = models.allowed_models ?? [];
  const aliases = models.aliases ?? {};
  const modelOptions = [
    { value: NONE, label: t("skillModelDefault"), icon: "auto_awesome" },
    ...allowed.map((m) => ({ value: m, label: aliases[m] ?? m, icon: "neurology" })),
  ];
  const styleOptions = [
    { value: NONE, label: t("skillStyleDefault") },
    { value: "corporate", label: t("skillStyleCorporate") },
    { value: "short", label: t("skillStyleShort") },
    { value: "instructive", label: t("skillStyleInstructive") },
    { value: "balanced", label: t("skillStyleBalanced") },
  ];

  const canSave = name.trim().length > 0 && slug.length > 0 && instructions.trim().length > 0;
  function toggleTool(tool: string) {
    setAllowedTools((current) =>
      current.includes(tool) ? current.filter((item) => item !== tool) : [...current, tool],
    );
  }

  function submit() {
    if (!canSave || saving) return;
    setDuplicate(false);
    setError(false);
    const style = STYLE_VALUES.includes(answerStyle as AnswerStyle)
      ? (answerStyle as AnswerStyle)
      : null;
    const body: SkillInput = {
      name: name.trim(),
      slug,
      description: description.trim() || null,
      instructions: instructions.trim(),
      icon: icon.trim() || null,
      model: model || null,
      answer_style: style,
      allowed_tools: allowedTools,
      enabled,
    };
    startSave(async () => {
      const res = editing
        ? await updateSkillAction(editing.id, body)
        : await createSkillAction(body);
      if (res.ok) {
        onClose();
        router.refresh();
      } else if (res.duplicate) {
        setDuplicate(true);
      } else {
        setError(true);
      }
    });
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="lg"
      title={editing ? t("skillEdit") : t("skillNew")}
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
        className="space-y-4"
      >
        <div className="grid gap-4 sm:grid-cols-2">
          {/* Name */}
          <div className="space-y-1.5">
            <label htmlFor="skill-name" className={ui.label}>
              {t("skillName")}
            </label>
            <input
              id="skill-name"
              value={name}
              onChange={(e) => onNameChange(e.target.value)}
              required
              className={ui.input}
              placeholder={t("skillNamePlaceholder")}
            />
          </div>
          {/* Slug (the slash command) */}
          <div className="space-y-1.5">
            <label htmlFor="skill-slug" className={ui.label}>
              {t("skillSlug")}
            </label>
            <div className="flex items-center gap-1.5">
              <span className="text-sm font-medium text-ink-muted">/</span>
              <input
                id="skill-slug"
                value={slug}
                onChange={(e) => onSlugChange(e.target.value)}
                required
                inputMode="text"
                autoCapitalize="off"
                autoCorrect="off"
                spellCheck={false}
                className={`${ui.input} font-mono`}
                placeholder={t("skillSlugPlaceholder")}
              />
            </div>
            <p className="text-xs text-ink-muted">{t("skillSlugHelp")}</p>
          </div>
        </div>

        {/* Description */}
        <div className="space-y-1.5">
          <label htmlFor="skill-desc" className={ui.label}>
            {t("skillDescription")}
          </label>
          <input
            id="skill-desc"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            className={ui.input}
            placeholder={t("skillDescriptionPlaceholder")}
          />
        </div>

        {/* Icon — visual picker */}
        <div className="space-y-1.5">
          <label className={ui.label}>{t("skillIcon")}</label>
          <IconPicker
            value={icon}
            onChange={setIcon}
            ariaLabel={t("skillIconPick")}
            searchPlaceholder={t("iconSearch")}
          />
          <p className="text-xs text-ink-muted">{t("skillIconHelp")}</p>
        </div>

        {/* Instructions (system prompt) + AI-generate affordance */}
        <div className="space-y-1.5">
          <label htmlFor="skill-instr" className={ui.label}>
            {t("skillInstructions")}
          </label>
          <SkillGenerate
            fallback={name}
            onGenerated={setInstructions}
            label={t("skillGenerate")}
            placeholder={t("skillGenerateDesc")}
            generatingLabel={t("skillGenerating")}
            errorLabel={t("skillGenerateError")}
          />
          <textarea
            id="skill-instr"
            value={instructions}
            onChange={(e) => setInstructions(e.target.value)}
            required
            rows={5}
            className={`${ui.input} h-auto resize-y py-2.5 leading-relaxed`}
            placeholder={t("skillInstructionsPlaceholder")}
          />
          <p className="text-xs text-ink-muted">{t("skillInstructionsHelp")}</p>
        </div>

        {/* Model + answer style */}
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <label className={ui.label}>{t("skillModel")}</label>
            <Select
              options={modelOptions}
              value={model}
              onValueChange={setModel}
              ariaLabel={t("skillModel")}
            />
          </div>
          <div className="space-y-1.5">
            <label className={ui.label}>{t("skillAnswerStyle")}</label>
            <Select
              options={styleOptions}
              value={answerStyle}
              onValueChange={setAnswerStyle}
              ariaLabel={t("skillAnswerStyle")}
            />
          </div>
        </div>

        <fieldset className="space-y-2">
          <legend className={ui.label}>{t("skillTools")}</legend>
          <p className="text-xs text-ink-muted">{t("skillToolsHelp")}</p>
          <div className="grid gap-2 sm:grid-cols-3">
            {TOOL_VALUES.map((tool) => {
              const label =
                tool === "web_search"
                  ? t("skillToolWeb")
                  : tool === "deep_research"
                    ? t("skillToolDeep")
                    : t("skillToolMcp");
              return (
                <label
                  key={tool}
                  className="flex cursor-pointer items-center gap-2 rounded-xl border border-border bg-surface px-3 py-2 text-sm text-ink"
                >
                  <input
                    type="checkbox"
                    checked={allowedTools.includes(tool)}
                    onChange={() => toggleTool(tool)}
                    className="h-4 w-4 accent-brand"
                  />
                  {label}
                </label>
              );
            })}
          </div>
        </fieldset>

        {/* Enabled toggle */}
        <button
          type="button"
          role="switch"
          aria-checked={enabled}
          onClick={() => setEnabled((v) => !v)}
          className="flex w-full items-center justify-between gap-4 rounded-2xl border border-border bg-surface px-4 py-3 text-left transition hover:bg-surface-2"
        >
          <span className="min-w-0">
            <span className="block text-sm font-medium text-ink">{t("skillEnabledLabel")}</span>
            <span className="mt-0.5 block text-xs text-ink-muted">{t("skillEnabledHelp")}</span>
          </span>
          <span
            aria-hidden
            className={`relative h-6 w-11 shrink-0 rounded-full transition-colors ${
              enabled ? "bg-brand" : "bg-surface-3"
            }`}
          >
            <span
              className={`absolute top-0.5 h-5 w-5 rounded-full bg-surface shadow-soft transition-transform ${
                enabled ? "left-0.5 translate-x-5" : "left-0.5"
              }`}
            />
          </span>
        </button>

        {duplicate && (
          <p className="rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger" role="alert">
            {t("skillDuplicateSlug")}
          </p>
        )}
        {error && (
          <p className="rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger" role="alert">
            {t("saveError")}
          </p>
        )}

        <div className="flex items-center justify-end gap-3 pt-1">
          <Button type="button" variant="ghost" onClick={onClose}>
            {tc("cancel")}
          </Button>
          <Button type="submit" disabled={!canSave || saving}>
            {saving ? tc("loading") : t("skillSave")}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

export default function SkillsClient({
  initial,
  models,
}: {
  initial: Skill[];
  models: ModelsConfig;
}) {
  const t = useTranslations("admin");
  const router = useRouter();
  const [pending, start] = useTransition();
  const [modal, setModal] = useState<{ open: boolean; editing: Skill | null }>({
    open: false,
    editing: null,
  });

  // Stable display order: enabled first, then alphabetical by name.
  const skills = useMemo(
    () =>
      [...initial].sort(
        (a, b) =>
          Number(b.enabled) - Number(a.enabled) || a.name.localeCompare(b.name),
      ),
    [initial],
  );

  function remove(s: Skill) {
    if (!window.confirm(t("skillConfirmDelete", { name: s.name }))) return;
    start(async () => {
      await deleteSkillAction(s.id);
      router.refresh();
    });
  }

  return (
    <div className="space-y-6">
      {/* What a skill is. */}
      <div className="flex items-start gap-3 rounded-2xl border border-border bg-surface-2/60 p-4 text-sm text-ink-muted">
        <Icon name="bolt" size={20} className="mt-0.5 shrink-0 text-brand" />
        <p>{t("skillsHint")}</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>{t("skillsList")}</CardTitle>
          <Button size="sm" onClick={() => setModal({ open: true, editing: null })}>
            <Icon name="add" size={18} />
            {t("skillNew")}
          </Button>
        </CardHeader>
        <CardBody>
          {skills.length === 0 ? (
            <EmptyState
              icon="bolt"
              title={t("skillNoneTitle")}
              description={t("skillNoneHint")}
              action={
                <Button size="sm" onClick={() => setModal({ open: true, editing: null })}>
                  <Icon name="add" size={18} />
                  {t("skillNew")}
                </Button>
              }
            />
          ) : (
            <ul className="grid gap-2 lg:grid-cols-2">
              {skills.map((s) => (
                <li
                  key={s.id}
                  className="group flex items-center gap-3 rounded-2xl border border-border bg-surface p-3 transition hover:border-brand/30"
                >
                  <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-brand/10 text-brand">
                    <Icon name={s.icon?.trim() || "bolt"} size={20} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="truncate font-medium text-ink">{s.name}</span>
                      <span className="shrink-0 font-mono text-xs text-brand">/{s.slug}</span>
                      <Badge tone={s.enabled ? "success" : "neutral"}>
                        {s.enabled ? t("skillEnabled") : t("skillDisabled")}
                      </Badge>
                    </div>
                    {s.description && (
                      <p className="mt-0.5 truncate text-xs text-ink-muted">{s.description}</p>
                    )}
                  </div>
                  <div className="flex shrink-0 items-center gap-1 opacity-60 transition group-hover:opacity-100">
                    <button
                      type="button"
                      title={t("skillEdit")}
                      aria-label={t("skillEdit")}
                      onClick={() => setModal({ open: true, editing: s })}
                      className="grid h-8 w-8 place-items-center rounded-lg text-ink-muted transition hover:bg-surface-2 hover:text-ink"
                    >
                      <Icon name="edit" size={18} />
                    </button>
                    <button
                      type="button"
                      title={t("skillDelete")}
                      aria-label={t("skillDelete")}
                      disabled={pending}
                      onClick={() => remove(s)}
                      className="grid h-8 w-8 place-items-center rounded-lg text-ink-muted transition hover:bg-surface-2 hover:text-danger disabled:opacity-40"
                    >
                      <Icon name="delete" size={18} />
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardBody>
      </Card>

      {/* Keyed so each open resets the form's internal state to the right skill. */}
      {modal.open && (
        <SkillModal
          key={modal.editing?.id ?? "new-skill"}
          open={modal.open}
          onClose={() => setModal({ open: false, editing: null })}
          editing={modal.editing}
          models={models}
        />
      )}
    </div>
  );
}
