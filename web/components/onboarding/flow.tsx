// SPDX-License-Identifier: Apache-2.0

"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { type FormEvent, useRef, useState, useTransition } from "react";

import {
  type BootstrapError,
  bootstrapAction,
  createWorkspaceAction,
  uploadAction,
} from "@/app/onboarding/actions";
import { BrandLogo, BrandName } from "@/components/branding-provider";
import { Icon } from "@/components/ui/icon";
import type { WorkspaceSetup } from "@/lib/api";
import { PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH } from "@/lib/password-policy";
import { ui } from "@/lib/ui";

type WizType = "INTERNAL" | "EXTERNAL";

function Shell({ step, children }: { step?: number; children: React.ReactNode }) {
  return (
    <main className="relative flex min-h-screen flex-col items-center justify-center bg-bg px-6 py-10 text-ink">
      <div className="spotlight" aria-hidden />
      <div className="w-full max-w-lg">
        <div className="mb-6 flex items-center gap-2.5 font-display text-lg font-semibold">
          <BrandLogo size={28} />
          <BrandName />
        </div>
        <div className="card space-y-6 p-7 shadow-[var(--shadow-lift)]">
          {step ? (
            <div className="flex gap-1.5" aria-hidden>
              {[1, 2, 3].map((s) => (
                <span
                  key={s}
                  className={`h-1.5 flex-1 rounded-full transition-colors ${
                    s <= step ? "bg-brand" : "bg-surface-3"
                  }`}
                />
              ))}
            </div>
          ) : null}
          {children}
        </div>
      </div>
    </main>
  );
}

export default function OnboardingFlow({
  needsBootstrap,
  setupTokenRequired,
}: {
  needsBootstrap: boolean;
  setupTokenRequired?: boolean;
}) {
  const t = useTranslations("onboarding");
  const ta = useTranslations("admin");
  const tc = useTranslations("common");
  const router = useRouter();

  const [phase, setPhase] = useState<"bootstrap" | "wizard">(
    needsBootstrap ? "bootstrap" : "wizard",
  );
  const [step, setStep] = useState(1);
  const [type, setType] = useState<WizType>("INTERNAL");
  const [setup, setSetup] = useState<WorkspaceSetup | null>(null);
  const [error, setError] = useState(false);
  const [bootstrapError, setBootstrapError] = useState<BootstrapError | null>(null);
  const [uploadMsg, setUploadMsg] = useState<string | null>(null);
  const [uploadRefused, setUploadRefused] = useState(false);
  const [fileCount, setFileCount] = useState(0);
  const [dragging, setDragging] = useState(false);
  const [copied, setCopied] = useState(false);
  const [pending, start] = useTransition();
  const fileRef = useRef<HTMLInputElement>(null);

  function onBootstrap(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    setBootstrapError(null);
    start(async () => {
      const r = await bootstrapAction(
        String(fd.get("email")),
        String(fd.get("password")),
        String(fd.get("orgName")),
        String(fd.get("setupToken") ?? ""),
      );
      if (r.ok) setPhase("wizard");
      else setBootstrapError(r.error ?? "failed");
    });
  }

  function onChooseType(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    const name = String(fd.get("workspaceName") || (type === "INTERNAL" ? "Team" : "Support"));
    const inviteEmail = String(fd.get("inviteEmail") || "");
    setError(false);
    start(async () => {
      const r = await createWorkspaceAction(type, name, inviteEmail || undefined);
      if (r.ok && r.setup) {
        setSetup(r.setup);
        setStep(2);
      } else {
        setError(true);
      }
    });
  }

  function onUpload(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!setup) return;
    const fd = new FormData(e.currentTarget);
    setUploadMsg(t("uploading"));
    setUploadRefused(false);
    start(async () => {
      const r = await uploadAction(setup.workspace.id, fd);
      setUploadRefused(Boolean(r.refusal));
      // Embedding-profile refusals reuse the knowledge-base messages.
      setUploadMsg(
        r.refusal
          ? "values" in r.refusal
            ? ta(r.refusal.key, r.refusal.values)
            : ta(r.refusal.key)
          : t("uploaded", { count: r.count }),
      );
    });
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragging(false);
    if (fileRef.current && e.dataTransfer.files.length) {
      fileRef.current.files = e.dataTransfer.files;
      setFileCount(e.dataTransfer.files.length);
    }
  }

  function copy(text: string) {
    void navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }

  if (phase === "bootstrap") {
    return (
      <Shell>
        <div className="space-y-1.5">
          <h1 className="font-display text-2xl font-semibold tracking-tight">{t("setupTitle")}</h1>
          <p className="text-sm text-ink-muted">{t("setupSubtitle")}</p>
        </div>
        <form onSubmit={onBootstrap} className="space-y-4">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
            {t("bootstrapTitle")}
          </h2>
          <div className="space-y-1.5">
            <label htmlFor="orgName" className={ui.label}>
              {t("orgName")}
            </label>
            <input id="orgName" name="orgName" required className={ui.input} />
          </div>
          <div className="space-y-1.5">
            <label htmlFor="bootstrap-email" className={ui.label}>
              {tc("email")}
            </label>
            <input
              id="bootstrap-email"
              name="email"
              type="email"
              required
              autoComplete="email"
              className={ui.input}
            />
          </div>
          <div className="space-y-1.5">
            <label htmlFor="bootstrap-password" className={ui.label}>
              {tc("password")}
            </label>
            <input
              id="bootstrap-password"
              name="password"
              type="password"
              required
              minLength={PASSWORD_MIN_LENGTH}
              maxLength={PASSWORD_MAX_LENGTH}
              autoComplete="new-password"
              aria-describedby={
                bootstrapError === "weak_password"
                  ? "bootstrap-password-hint bootstrap-error"
                  : "bootstrap-password-hint"
              }
              aria-invalid={bootstrapError === "weak_password" || undefined}
              className={ui.input}
            />
            <p id="bootstrap-password-hint" className="text-xs text-ink-muted">
              {tc("passwordHint", { min: PASSWORD_MIN_LENGTH })}
            </p>
          </div>
          {setupTokenRequired !== false && (
            <div className="space-y-1.5">
              <label htmlFor="bootstrap-setup-token" className={ui.label}>
                {t("setupToken")}
              </label>
              <input
                id="bootstrap-setup-token"
                name="setupToken"
                type="text"
                required={setupTokenRequired === true}
                autoComplete="off"
                spellCheck={false}
                aria-describedby={
                  bootstrapError === "invalid_token"
                    ? "bootstrap-setup-token-hint bootstrap-error"
                    : "bootstrap-setup-token-hint"
                }
                aria-invalid={bootstrapError === "invalid_token" || undefined}
                className={`${ui.input} font-mono`}
              />
              <p id="bootstrap-setup-token-hint" className="text-xs text-ink-muted">
                {t("setupTokenHint")}
              </p>
            </div>
          )}
          {bootstrapError && (
            <p id="bootstrap-error" role="alert" className="rounded-xl bg-danger/10 px-3.5 py-2.5 text-sm text-danger">
              {bootstrapError === "invalid_token"
                ? t("setupTokenInvalid")
                : bootstrapError === "already_setup"
                  ? t("bootstrapAlreadySetup")
                  : bootstrapError === "weak_password"
                    ? tc("passwordPolicyError", { min: PASSWORD_MIN_LENGTH, max: PASSWORD_MAX_LENGTH })
                    : t("bootstrapError")}
            </p>
          )}
          <button type="submit" disabled={pending} className={`${ui.btnPrimary} w-full py-3.5`}>
            {pending ? tc("loading") : t("createAdmin")}
          </button>
        </form>
      </Shell>
    );
  }

  if (step === 1) {
    return (
      <Shell step={1}>
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-brand">
            {t("step", { n: 1 })}
          </p>
          <h1 className="mt-1.5 font-display text-xl font-semibold tracking-tight">
            {t("step1Title")}
          </h1>
        </div>
        <form onSubmit={onChooseType} className="space-y-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {(["INTERNAL", "EXTERNAL"] as const).map((opt) => {
              const selected = type === opt;
              return (
                <button
                  type="button"
                  key={opt}
                  onClick={() => setType(opt)}
                  aria-pressed={selected}
                  className={`rounded-2xl border p-4 text-left transition ${
                    selected
                      ? "border-brand bg-brand/5 ring-2 ring-brand/30"
                      : "border-border hover:border-ink-muted/40"
                  }`}
                >
                  <span
                    className={`grid h-9 w-9 place-items-center rounded-xl transition-colors ${
                      selected ? "bg-brand/10 text-brand" : "bg-surface-2 text-ink-muted"
                    }`}
                  >
                    <Icon name={opt === "INTERNAL" ? "groups" : "support_agent"} size={20} />
                  </span>
                  <div className="mt-3 font-semibold text-ink">
                    {opt === "INTERNAL" ? t("internalTitle") : t("externalTitle")}
                  </div>
                  <div className="mt-1 text-sm text-ink-muted">
                    {opt === "INTERNAL" ? t("internalDesc") : t("externalDesc")}
                  </div>
                </button>
              );
            })}
          </div>
          <div className="space-y-1.5">
            <label htmlFor="workspaceName" className={ui.label}>
              {t("workspaceName")}
            </label>
            <input id="workspaceName" name="workspaceName" className={ui.input} />
          </div>
          {type === "INTERNAL" && (
            <div className="space-y-1.5">
              <label htmlFor="inviteEmail" className={ui.label}>
                {t("inviteEmail")}
              </label>
              <input id="inviteEmail" name="inviteEmail" type="email" className={ui.input} />
            </div>
          )}
          {error && (
            <p className="rounded-xl bg-danger/10 px-3.5 py-2.5 text-sm text-danger">
              {t("bootstrapError")}
            </p>
          )}
          <button type="submit" disabled={pending} className={`${ui.btnPrimary} w-full py-3.5`}>
            {pending ? tc("loading") : tc("continue")}
          </button>
        </form>
      </Shell>
    );
  }

  if (step === 2) {
    return (
      <Shell step={2}>
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-brand">
            {t("step", { n: 2 })}
          </p>
          <h1 className="mt-1.5 font-display text-xl font-semibold tracking-tight">
            {t("step2Title")}
          </h1>
          <p className="mt-1.5 text-sm text-ink-muted">{t("step2Desc")}</p>
        </div>
        <form onSubmit={onUpload} className="space-y-4">
          <label
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed p-8 text-center transition ${
              dragging ? "border-brand bg-brand/5" : "border-border hover:border-brand/50"
            }`}
          >
            <span className="grid h-11 w-11 place-items-center rounded-2xl bg-surface-2 text-ink-muted">
              <Icon name="upload_file" size={22} />
            </span>
            <span className="mt-1 text-sm font-medium text-ink">
              {fileCount > 0 ? t("filesReady", { count: fileCount }) : t("chooseFiles")}
            </span>
            <span className="text-xs text-ink-muted">PDF · DOCX · XLSX · PPTX · TXT</span>
            <input
              ref={fileRef}
              type="file"
              name="files"
              multiple
              accept=".pdf,.docx,.xlsx,.pptx,.txt"
              onChange={(e) => setFileCount(e.target.files?.length ?? 0)}
              className="hidden"
            />
          </label>
          {uploadMsg && (
            <p
              className={`flex items-center gap-2 text-sm ${uploadRefused ? "text-danger" : "text-success"}`}
              role={uploadRefused ? "alert" : undefined}
            >
              <Icon
                name={pending ? "progress_activity" : uploadRefused ? "error" : "check_circle"}
                size={18}
                fill={!pending}
              />
              {uploadMsg}
            </p>
          )}
          <div className="flex gap-3">
            <button
              type="submit"
              disabled={pending || fileCount === 0}
              className={`${ui.btnPrimary} flex-1 py-3.5`}
            >
              {pending ? t("uploading") : t("chooseFiles")}
            </button>
            <button type="button" onClick={() => setStep(3)} className={`${ui.btnGhost} py-3.5`}>
              {t("skip")}
            </button>
          </div>
        </form>
      </Shell>
    );
  }

  // step 3
  const inviteUrl =
    setup?.invite_accept_path && typeof window !== "undefined"
      ? `${window.location.origin}${setup.invite_accept_path}`
      : (setup?.invite_token ?? "");
  const isExternal = type === "EXTERNAL" && Boolean(setup?.embed_snippet);
  const shareText = isExternal ? (setup?.embed_snippet ?? "") : inviteUrl;

  return (
    <Shell step={3}>
      <div className="text-center">
        <span className="mx-auto grid h-12 w-12 place-items-center rounded-2xl bg-brand/10 text-brand">
          <Icon name="check_circle" size={26} fill />
        </span>
        <p className="mt-3 text-xs font-semibold uppercase tracking-wider text-brand">
          {t("step", { n: 3 })}
        </p>
        <h1 className="mt-1.5 font-display text-xl font-semibold tracking-tight">
          {isExternal ? t("step3TitleExternal") : t("step3TitleInternal")}
        </h1>
        <p className="mt-1.5 text-sm text-ink-muted">
          {isExternal ? t("embedHint") : t("inviteHint")}
        </p>
      </div>
      <div className="flex items-stretch gap-2">
        <code className="block w-full overflow-x-auto rounded-xl border border-border bg-surface-2 p-3 font-mono text-xs text-ink">
          {shareText}
        </code>
        <button type="button" onClick={() => copy(shareText)} className={ui.btnGhost}>
          {copied ? tc("copied") : tc("copy")}
        </button>
      </div>
      <button
        type="button"
        onClick={() => router.push("/dashboard")}
        className={`${ui.btnPrimary} w-full py-3.5`}
      >
        {t("finish")}
        <Icon name="arrow_forward" size={18} />
      </button>
    </Shell>
  );
}
