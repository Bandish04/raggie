// SPDX-License-Identifier: Apache-2.0

"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { createMySkillAction, updateMySkillAction } from "@/app/chat/skill-actions";
import IconPicker from "@/components/ui/icon-picker";
import { Modal } from "@/components/ui/modal";
import Select from "@/components/ui/select";
import SkillGenerate from "@/components/ui/skill-generate";
import type { AnswerStyle, ModelsConfig, Skill } from "@/lib/api";
// Constrain free text to the slug grammar the backend accepts (a-z, 0-9, -;
// <=32). Applied live as the user types so the "/command" helper never lies.
export function slugify(raw: string): string {
  return raw
    .toLowerCase()
    .replace(/[^a-z0-9-]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-+/, "")
    .slice(0, 32);
}

// Answer-style values the backend accepts (the select's non-"" options).
export const SKILL_STYLE_VALUES: AnswerStyle[] = ["corporate", "short", "instructive", "balanced"];

export const SKILL_TOOL_VALUES = ["web_search", "deep_research", "mcp"] as const;

/* Create / edit a PERSONAL skill, from chat. Mirrors the admin SkillModal's
   field set minus org governance (no enabled toggle / description is optional).
   Submits via the personal server actions, then router.refresh() so chat/page
   re-fetches the union (menu + "/command" picker pick up the change). */
export function PersonalSkillModal({
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
  const t = useTranslations("chat");
  const tc = useTranslations("common");
  const router = useRouter();
  const [saving, startSave] = useTransition();

  const [name, setName] = useState(editing?.name ?? "");
  // The slug tracks the name until the user edits it directly, then it sticks.
  // On edit it is already dirty so we never clobber an existing command.
  const [slug, setSlug] = useState(editing?.slug ?? "");
  const [slugDirty, setSlugDirty] = useState(!!editing);
  const [icon, setIcon] = useState(editing?.icon ?? "");
  const [instructions, setInstructions] = useState(editing?.instructions ?? "");
  const [model, setModel] = useState(editing?.model ?? "");
  const [answerStyle, setAnswerStyle] = useState<string>(editing?.answer_style ?? "");
  const [allowedTools, setAllowedTools] = useState<string[]>(editing?.allowed_tools ?? []);

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
    { value: "", label: t("skillModelDefault"), icon: "auto_awesome" },
    ...allowed.map((m) => ({ value: m, label: aliases[m] ?? m, icon: "neurology" })),
  ];
  const styleOptions = [
    { value: "", label: t("skillStyleDefault") },
    { value: "corporate", label: t("skillStyleCorporate") },
    { value: "short", label: t("skillStyleShort") },
    { value: "instructive", label: t("skillStyleInstructive") },
    { value: "balanced", label: t("skillStyleBalanced") },
  ];

  const canSave =
    name.trim().length > 0 && slug.length > 0 && instructions.trim().length > 0;
  function toggleTool(tool: string) {
    setAllowedTools((current) =>
      current.includes(tool) ? current.filter((item) => item !== tool) : [...current, tool],
    );
  }

  function submit() {
    if (!canSave || saving) return;
    setDuplicate(false);
    setError(false);
    const fd = new FormData();
    if (editing) fd.set("id", editing.id);
    fd.set("name", name.trim());
    fd.set("slug", slug);
    fd.set("icon", icon.trim());
    fd.set("instructions", instructions.trim());
    fd.set("model", model);
    fd.set(
      "answer_style",
      SKILL_STYLE_VALUES.includes(answerStyle as AnswerStyle) ? answerStyle : "",
    );
    allowedTools.forEach((tool) => fd.append("allowed_tools", tool));
    startSave(async () => {
      const res = editing
        ? await updateMySkillAction({}, fd)
        : await createMySkillAction({}, fd);
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
    <Modal open={open} onClose={onClose} size="lg" title={editing ? t("skillEdit") : t("skillNew")}>
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
            <label htmlFor="pskill-name" className="text-sm font-medium text-ink">
              {t("skillName")}
            </label>
            <input
              id="pskill-name"
              value={name}
              onChange={(e) => onNameChange(e.target.value)}
              required
              className="h-10 w-full rounded-xl border border-border bg-surface px-3 text-sm text-ink outline-none transition placeholder:text-ink-muted/60 focus:border-brand"
              placeholder={t("skillNamePlaceholder")}
            />
          </div>
          {/* Slug (the slash command) */}
          <div className="space-y-1.5">
            <label htmlFor="pskill-slug" className="text-sm font-medium text-ink">
              {t("skillSlug")}
            </label>
            <div className="flex items-center gap-1.5">
              <span className="text-sm font-medium text-ink-muted">/</span>
              <input
                id="pskill-slug"
                value={slug}
                onChange={(e) => onSlugChange(e.target.value)}
                required
                autoCapitalize="off"
                autoCorrect="off"
                spellCheck={false}
                className="h-10 w-full rounded-xl border border-border bg-surface px-3 font-mono text-sm text-ink outline-none transition placeholder:text-ink-muted/60 focus:border-brand"
                placeholder={t("skillSlugPlaceholder")}
              />
            </div>
            <p className="text-xs text-ink-muted">{t("skillSlugHelp")}</p>
          </div>
        </div>

        <fieldset className="space-y-2">
          <legend className="text-sm font-medium text-ink">{t("skillTools")}</legend>
          <p className="text-xs text-ink-muted">{t("skillToolsHelp")}</p>
          <div className="grid gap-2 sm:grid-cols-3">
            {SKILL_TOOL_VALUES.map((tool) => {
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

        {/* Icon — visual picker */}
        <div className="space-y-1.5">
          <label className="text-sm font-medium text-ink">{t("skillIcon")}</label>
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
          <label htmlFor="pskill-instr" className="text-sm font-medium text-ink">
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
            id="pskill-instr"
            value={instructions}
            onChange={(e) => setInstructions(e.target.value)}
            required
            rows={5}
            className="w-full resize-y rounded-xl border border-border bg-surface px-3 py-2.5 text-sm leading-relaxed text-ink outline-none transition placeholder:text-ink-muted/60 focus:border-brand"
            placeholder={t("skillInstructionsPlaceholder")}
          />
          <p className="text-xs text-ink-muted">{t("skillInstructionsHelp")}</p>
        </div>

        {/* Model + answer style */}
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <label className="text-sm font-medium text-ink">{t("skillModel")}</label>
            <Select
              options={modelOptions}
              value={model}
              onValueChange={setModel}
              ariaLabel={t("skillModel")}
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-sm font-medium text-ink">{t("skillAnswerStyle")}</label>
            <Select
              options={styleOptions}
              value={answerStyle}
              onValueChange={setAnswerStyle}
              ariaLabel={t("skillAnswerStyle")}
            />
          </div>
        </div>

        {duplicate && (
          <p className="rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger" role="alert">
            {t("skillDuplicateSlug")}
          </p>
        )}
        {error && (
          <p className="rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger" role="alert">
            {t("skillSaveError")}
          </p>
        )}

        <div className="flex items-center justify-end gap-3 pt-1">
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl px-4 py-2 text-sm font-medium text-ink-muted transition hover:bg-surface-2 hover:text-ink"
          >
            {tc("cancel")}
          </button>
          <button
            type="submit"
            disabled={!canSave || saving}
            className="rounded-xl bg-brand px-4 py-2 text-sm font-medium text-white transition hover:bg-brand/90 disabled:opacity-40"
          >
            {saving ? tc("loading") : t("skillSave")}
          </button>
        </div>
      </form>
    </Modal>
  );
}
