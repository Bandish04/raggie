// SPDX-License-Identifier: Apache-2.0

"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { type DragEvent, useRef, useState } from "react";

import { uploadFileResumable } from "@/lib/upload";
import { uploadFailureMessage, type UploadFailureMessage } from "@/lib/upload-errors";
import type { WorkspaceSummary } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import Select from "@/components/ui/select";

// Compact uploader used in the team detail "document pool". Delegates to the
// shared resumable uploader so there is a single upload code path in the app.
export default function UploadControl({ workspaces }: { workspaces: WorkspaceSummary[] }) {
  const t = useTranslations("admin");
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [wsId, setWsId] = useState(workspaces[0]?.id ?? "");
  const [names, setNames] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  // Set when the embedding profile refused the upload (shown instead of the generic error).
  const [friendly, setFriendly] = useState<UploadFailureMessage | null>(null);

  if (workspaces.length === 0) return null;

  const sync = () => setNames(Array.from(inputRef.current?.files ?? []).map((f) => f.name));

  function onDrop(e: DragEvent) {
    e.preventDefault();
    if (inputRef.current && e.dataTransfer.files.length) {
      inputRef.current.files = e.dataTransfer.files;
      sync();
    }
  }

  async function submit() {
    const files = Array.from(inputRef.current?.files ?? []);
    if (files.length === 0 || !wsId) return;
    setBusy(true);
    setError(false);
    setFriendly(null);
    let failed = false;
    for (const file of files) {
      const result = await uploadFileResumable(wsId, file);
      if (!result.ok && !result.aborted) {
        failed = true;
        const message = uploadFailureMessage(result);
        if (message) {
          // The profile blocks every file the same way; stop here.
          setFriendly(message);
          break;
        }
      }
    }
    setBusy(false);
    setError(failed);
    if (!failed) {
      setNames([]);
      if (inputRef.current) inputRef.current.value = "";
      router.refresh();
    }
  }

  return (
    <div className="mb-6 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-display text-lg font-semibold">{t("upload")}</h2>
          <p className="mt-0.5 text-sm text-ink-muted">{t("uploadHint")}</p>
        </div>
        <div className="flex items-center gap-3">
          {workspaces.length > 1 ? (
            <Select
              size="sm"
              value={wsId}
              onValueChange={setWsId}
              ariaLabel={t("upload")}
              options={workspaces.map((w) => ({ value: w.id, label: w.name }))}
            />
          ) : null}
          <Button disabled={busy || names.length === 0} onClick={submit}>
            {busy ? t("uploading") : t("uploadCta")}
          </Button>
        </div>
      </div>

      <label
        onDragOver={(e) => e.preventDefault()}
        onDrop={onDrop}
        className="flex cursor-pointer flex-col items-center justify-center gap-3 rounded-3xl border-2 border-dashed border-border bg-surface px-6 py-12 text-center transition hover:bg-surface-2"
      >
        <span className="grid h-12 w-12 place-items-center rounded-2xl bg-brand/10 text-brand">
          <Icon name="upload_file" size={24} />
        </span>
        <span className="text-sm font-medium text-ink">{t("dropHere")}</span>
        <span className="text-xs text-ink-muted">{t("uploadLargeHint")}</span>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept=".pdf,.docx,.xlsx,.pptx,.txt,.md,.png,.jpg,.jpeg,.tif,.tiff,.webp,.bmp"
          onChange={sync}
          className="hidden"
        />
      </label>

      {names.length > 0 ? (
        <div className="flex flex-wrap gap-2">
          {names.map((n) => (
            <span
              key={n}
              className="inline-flex items-center gap-1.5 rounded-full bg-surface-2 px-3 py-1 text-xs text-ink"
            >
              <Icon name="description" size={14} className="text-ink-muted" />
              {n}
            </span>
          ))}
        </div>
      ) : null}

      {error ? (
        <p className="text-sm text-danger" role="alert">
          {friendly
            ? "values" in friendly
              ? t(friendly.key, friendly.values)
              : t(friendly.key)
            : t("uploadFailed")}
        </p>
      ) : null}
    </div>
  );
}
