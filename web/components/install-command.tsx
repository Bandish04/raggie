// SPDX-License-Identifier: Apache-2.0

"use client";

import { useState, useSyncExternalStore } from "react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";

const FALLBACK_ORIGIN = "https://your-raggie-site.example";

function subscribe() {
  return () => {};
}

function getSnapshot() {
  return typeof window === "undefined" ? FALLBACK_ORIGIN : window.location.origin;
}

export function InstallCommand() {
  const t = useTranslations("landing");
  const [copied, setCopied] = useState(false);
  const origin = useSyncExternalStore(subscribe, getSnapshot, () => FALLBACK_ORIGIN);
  const command = `curl -fsSL ${origin}/install.sh | bash`;

  function copy() {
    void navigator.clipboard.writeText(command).then(() => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    });
  }

  return (
    <div className="overflow-hidden rounded-[2rem] border border-white/10 bg-[#0b0b0d] text-white shadow-[0_30px_80px_-32px_rgba(10,91,255,0.38)]">
      <div className="flex items-center justify-between border-b border-white/10 px-5 py-4">
        <div>
          <div className="text-[0.7rem] font-semibold uppercase tracking-[0.24em] text-white/45">
            {t("installEyebrow")}
          </div>
          <div className="mt-1 text-sm text-white/72">{t("installBody")}</div>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={copy}
          className="border-white/14 bg-white/4 text-white hover:bg-white/10"
        >
          <Icon name={copied ? "check" : "content_copy"} size={16} />
          {copied ? t("installCopied") : t("installCopy")}
        </Button>
      </div>

      <div className="space-y-4 px-5 py-5">
        <pre className="overflow-x-auto whitespace-pre-wrap break-all rounded-2xl border border-white/10 bg-white/4 p-4 text-[0.95rem] leading-7 text-white/92">
          <code suppressHydrationWarning>{command}</code>
        </pre>

        <div className="grid gap-2 text-sm text-white/65">
          <div className="flex items-start gap-2">
            <Icon name="download" size={16} className="mt-0.5 text-brand" />
            <span>{t("installNoteFetch")}</span>
          </div>
          <div className="flex items-start gap-2">
            <Icon name="vpn_key" size={16} className="mt-0.5 text-brand" />
            <span>{t("installNoteSecrets")}</span>
          </div>
          <div className="flex items-start gap-2">
            <Icon name="admin_panel_settings" size={16} className="mt-0.5 text-brand" />
            <span>{t("installNoteOnboarding")}</span>
          </div>
        </div>
      </div>
    </div>
  );
}
