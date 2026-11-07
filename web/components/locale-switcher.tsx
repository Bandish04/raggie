// SPDX-License-Identifier: Apache-2.0

"use client";

import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useTransition } from "react";

import { setLocale } from "@/app/actions/locale";

const LOCALES = ["tr", "en"] as const;

export default function LocaleSwitcher() {
  const current = useLocale();
  const router = useRouter();
  const t = useTranslations("common");
  const [pending, start] = useTransition();

  const change = (locale: "tr" | "en") => {
    if (locale === current || pending) return;
    start(async () => {
      await setLocale(locale);
      router.refresh(); // re-render the RSC tree in the new locale — no full reload
    });
  };

  return (
    <div
      role="group"
      aria-label={t("language")}
      className={`inline-flex rounded-full border border-border bg-surface-2 p-0.5 text-xs font-medium transition-opacity ${
        pending ? "opacity-60" : ""
      }`}
    >
      {LOCALES.map((l) => (
        <button
          key={l}
          type="button"
          onClick={() => change(l)}
          disabled={pending}
          aria-pressed={l === current}
          className={`rounded-full px-2.5 py-1 transition ${
            l === current ? "bg-brand text-brand-contrast" : "text-ink-muted hover:text-ink"
          }`}
        >
          {l.toUpperCase()}
        </button>
      ))}
    </div>
  );
}
