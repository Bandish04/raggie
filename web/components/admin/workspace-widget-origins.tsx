// SPDX-License-Identifier: Apache-2.0

"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState, useTransition, type FormEvent } from "react";

import { setWidgetOriginsAction } from "@/app/admin/workspaces/actions";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Modal } from "@/components/ui/modal";
import { ui } from "@/lib/ui";
import { addOrigin, removeOrigin, type OriginError } from "@/lib/widget-origins";

const ORIGIN_ERROR_KEY = {
  empty: "widgetOriginErrorEmpty",
  wildcard: "widgetOriginErrorWildcard",
  scheme: "widgetOriginErrorScheme",
  path: "widgetOriginErrorPath",
  invalid: "widgetOriginErrorInvalid",
  duplicate: "widgetOriginErrorDuplicate",
} as const satisfies Record<OriginError, string>;

const SAVE_ERROR_KEY = {
  invalid: "widgetOriginsSaveInvalid",
  forbidden: "widgetOriginsSaveForbidden",
  failed: "widgetOriginsSaveFailed",
} as const;

// Per-workspace editor for the widget allow-list. Edits a draft in a modal and
// saves the whole list in one PUT; Cancel discards the draft.
export default function WorkspaceWidgetOrigins({
  workspaceId,
  workspaceName,
  origins,
}: {
  workspaceId: string;
  workspaceName: string;
  origins: string[];
}) {
  const t = useTranslations("admin");
  const tc = useTranslations("common");
  const router = useRouter();
  const [saved, setSaved] = useState(origins);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<string[]>(origins);
  const [input, setInput] = useState("");
  const [inputError, setInputError] = useState<OriginError | null>(null);
  const [saveError, setSaveError] = useState<keyof typeof SAVE_ERROR_KEY | null>(null);
  const [pending, start] = useTransition();

  function openEditor() {
    setDraft(saved);
    setInput("");
    setInputError(null);
    setSaveError(null);
    setOpen(true);
  }

  function add(e: FormEvent) {
    e.preventDefault();
    const result = addOrigin(draft, input);
    if (!result.ok) {
      setInputError(result.reason);
      return;
    }
    setDraft(result.origins);
    setInput("");
    setInputError(null);
  }

  function save() {
    setSaveError(null);
    start(async () => {
      const result = await setWidgetOriginsAction(workspaceId, draft);
      if (!result.ok) {
        setSaveError(result.error);
        return;
      }
      setSaved(result.origins);
      setOpen(false);
      router.refresh();
    });
  }

  const dirty = draft.length !== saved.length || draft.some((o, i) => o !== saved[i]);

  return (
    <>
      <button
        type="button"
        onClick={openEditor}
        className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full bg-surface-2 px-2.5 py-1 text-xs text-ink-muted transition hover:bg-surface-3 hover:text-ink"
      >
        <Icon name="language" size={14} />
        {t("widgetOriginsCount", { count: saved.length })}
      </button>

      <Modal
        open={open}
        onClose={() => !pending && setOpen(false)}
        title={t("widgetOriginsTitle", { name: workspaceName })}
        description={t("widgetOriginsDescription")}
        footer={
          <>
            <Button variant="ghost" onClick={() => setOpen(false)} disabled={pending}>
              {tc("cancel")}
            </Button>
            <Button onClick={save} disabled={pending || !dirty}>
              {tc("save")}
            </Button>
          </>
        }
      >
        <form onSubmit={add} noValidate>
          <label htmlFor={`origin-${workspaceId}`} className={ui.label}>
            {t("widgetOriginsLabel")}
          </label>
          <div className="mt-1.5 flex gap-2">
            <input
              id={`origin-${workspaceId}`}
              value={input}
              onChange={(e) => {
                setInput(e.target.value);
                if (inputError) setInputError(null);
              }}
              placeholder={t("widgetOriginsPlaceholder")}
              inputMode="url"
              autoComplete="off"
              spellCheck={false}
              aria-invalid={inputError ? true : undefined}
              aria-describedby={inputError ? `origin-${workspaceId}-error` : undefined}
              className={ui.input}
            />
            <Button type="submit" variant="ghost" disabled={pending}>
              {t("widgetOriginsAdd")}
            </Button>
          </div>
          {inputError ? (
            <p id={`origin-${workspaceId}-error`} role="alert" className="mt-1.5 text-sm text-danger">
              {t(ORIGIN_ERROR_KEY[inputError])}
            </p>
          ) : null}
        </form>

        {draft.length === 0 ? (
          <p className="mt-4 rounded-2xl border border-dashed border-border px-4 py-5 text-center text-sm text-ink-muted">
            {t("widgetOriginsEmpty")}
          </p>
        ) : (
          <ul className={`mt-4 ${ui.fieldGroup}`}>
            {draft.map((origin) => (
              <li key={origin} className="flex items-center justify-between gap-3 px-4 py-2.5">
                <span className="truncate font-mono text-sm text-ink">{origin}</span>
                <button
                  type="button"
                  onClick={() => setDraft(removeOrigin(draft, origin))}
                  disabled={pending}
                  aria-label={t("widgetOriginsRemove", { origin })}
                  className="grid h-8 w-8 shrink-0 place-items-center rounded-full text-ink-muted transition hover:bg-surface-2 hover:text-danger"
                >
                  <Icon name="close" size={18} />
                </button>
              </li>
            ))}
          </ul>
        )}

        {saveError ? (
          <p role="alert" className="mt-3 text-sm text-danger">
            {t(SAVE_ERROR_KEY[saveError])}
          </p>
        ) : null}
      </Modal>
    </>
  );
}
