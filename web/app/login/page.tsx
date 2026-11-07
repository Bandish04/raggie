// SPDX-License-Identifier: Apache-2.0

"use client";

import { useTranslations } from "next-intl";
import { useActionState } from "react";
import type { CSSProperties } from "react";

import { loginAction, type LoginState } from "./actions";
import { BrandLogo, BrandName, useBranding } from "@/components/branding-provider";
import { ui } from "@/lib/ui";

const delay = (ms: number): CSSProperties => ({ ["--d" as string]: `${ms}ms` });

export default function LoginPage() {
  const t = useTranslations();
  const { tagline } = useBranding();
  const [state, action, pending] = useActionState<LoginState, FormData>(loginAction, {});

  return (
    <main className="relative min-h-screen overflow-hidden">
      <div className="spotlight" aria-hidden />
      <div className="gridlines" aria-hidden />

      <header className="relative flex items-center gap-3 px-6 py-6 sm:px-10">
        <span className="flex items-center gap-2 font-display text-lg font-semibold">
          <BrandLogo size={28} /> <BrandName />
        </span>
        {tagline && (
          <span className="hidden text-sm text-ink-muted sm:inline">{tagline}</span>
        )}
      </header>

      <div className="relative mx-auto grid min-h-[calc(100vh-5.5rem)] max-w-6xl grid-cols-1 items-center gap-14 px-6 pb-20 sm:px-10 lg:grid-cols-12 lg:gap-8">
        {/* Editorial statement */}
        <section className="lg:col-span-7">
          <p className="rise text-xs font-semibold uppercase tracking-[0.22em] text-ink-muted" style={delay(0)}>
            {t("common.tagline")}
          </p>
          <h1
            className="rise mt-6 text-balance text-[3.25rem] font-semibold leading-[0.94] tracking-[-0.04em] sm:text-7xl lg:text-[5.25rem]"
            style={delay(80)}
          >
            {t("landing.headlineLead")}
            <br />
            <span className="text-brand">{t("landing.headlineAccent")}</span>
          </h1>
          <div className="rise mt-10 flex flex-wrap gap-2 text-xs font-medium text-ink-muted" style={delay(160)}>
            {["KVKK", "GDPR", "On-premise", "Self-hosted"].map((b) => (
              <span key={b} className="rounded-full border border-border px-3 py-1.5">
                {b}
              </span>
            ))}
          </div>
        </section>

        {/* Sign-in */}
        <section className="rise lg:col-span-5" style={delay(220)}>
          <div className="card ml-auto w-full max-w-sm p-7 shadow-[var(--shadow-lift)]">
            <h2 className="font-display text-2xl font-semibold">{t("login.title")}</h2>
            <p className="mt-1.5 text-[15px] text-ink-muted">{t("login.subtitle")}</p>

            <form action={action} className="mt-7 space-y-3">
              <div className={ui.fieldGroup}>
                <input
                  name="email"
                  type="email"
                  required
                  autoComplete="email"
                  aria-label={t("common.email")}
                  aria-invalid={state?.error === "invalid" || undefined}
                  aria-describedby={state?.error ? "login-error" : undefined}
                  placeholder={t("common.email")}
                  className={ui.fieldRow}
                />
                <input
                  name="password"
                  type="password"
                  required
                  autoComplete="current-password"
                  aria-label={t("common.password")}
                  aria-invalid={state?.error === "invalid" || undefined}
                  aria-describedby={state?.error ? "login-error" : undefined}
                  placeholder={t("common.password")}
                  className={ui.fieldRow}
                />
              </div>

              {state?.error && (
                <p id="login-error" className="text-sm text-danger" role="alert">
                  {state.error === "locked"
                    ? state.retryAfterMinutes
                      ? t("login.lockedFor", { minutes: state.retryAfterMinutes })
                      : t("login.locked")
                    : state.error === "unavailable"
                      ? t("login.unavailable")
                      : t("login.invalid")}
                </p>
              )}

              <button
                type="submit"
                disabled={pending}
                className={`${ui.btnPrimary} w-full !py-3.5 text-[15px]`}
              >
                {pending ? t("common.loading") : t("login.submit")}
              </button>
            </form>

            <p className="mt-8 text-xs text-ink-muted">© Raggie — data sovereignty, by design.</p>
          </div>
        </section>
      </div>
    </main>
  );
}
