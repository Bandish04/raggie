// SPDX-License-Identifier: Apache-2.0

import { getTranslations } from "next-intl/server";
import Link from "next/link";

import { BrandLogo, BrandName } from "@/components/branding-provider";
import { InstallCommand } from "@/components/install-command";
import { Badge } from "@/components/ui/badge";
import { Icon } from "@/components/ui/icon";
import { getBranding } from "@/lib/api";
import { ui } from "@/lib/ui";

const TRUST_BADGES = ["KVKK", "GDPR", "On-premise", "Self-hosted"] as const;

export default async function Home() {
  const t = await getTranslations();
  const { tagline } = await getBranding();
  const steps = [
    {
      id: "01",
      title: t("landing.stepInstallTitle"),
      body: t("landing.stepInstallBody"),
    },
    {
      id: "02",
      title: t("landing.stepAdminTitle"),
      body: t("landing.stepAdminBody"),
    },
    {
      id: "03",
      title: t("landing.stepWorkspaceTitle"),
      body: t("landing.stepWorkspaceBody"),
    },
  ];
  const features = [
    {
      title: t("landing.featureDeployTitle"),
      body: t("landing.featureDeployBody"),
    },
    {
      title: t("landing.featureGroundedTitle"),
      body: t("landing.featureGroundedBody"),
    },
    {
      title: t("landing.featureModesTitle"),
      body: t("landing.featureModesBody"),
    },
  ];

  return (
    <main className="relative overflow-hidden bg-bg text-ink">
      <div className="grain" aria-hidden />
      <div className="hero-wash" aria-hidden />
      <div className="spotlight" aria-hidden />

      <header className="mx-auto flex w-full max-w-5xl items-center justify-between px-6 py-6">
        <span className="flex items-center gap-2.5 font-display text-lg font-semibold">
          <BrandLogo size={28} />
          <BrandName />
          {tagline && (
            <span className="hidden text-sm font-normal text-ink-muted sm:inline">{tagline}</span>
          )}
        </span>
        <Link
          href="/login"
          className="text-sm font-medium text-ink-muted transition-colors hover:text-ink"
        >
          {t("common.signIn")}
        </Link>
      </header>

      <section className="relative">
        <div className="gridlines opacity-70" aria-hidden />
        <div className="mx-auto flex min-h-[calc(100svh-5.25rem)] w-full max-w-6xl items-center px-6 pb-20 pt-6">
          <div className="grid w-full gap-12 lg:grid-cols-[minmax(0,1.05fr)_minmax(22rem,0.95fr)] lg:items-end">
            <div className="max-w-3xl">
              <Badge tone="brand" dot className="mb-7">
                {t("landing.eyebrow")}
              </Badge>

              <h1 className="max-w-3xl text-balance font-display text-5xl font-semibold leading-[0.98] tracking-[-0.03em] sm:text-6xl lg:text-7xl">
                {t("landing.headlineLead")}{" "}
                <span className="text-brand">{t("landing.headlineAccent")}</span>
              </h1>

              <p className="mt-6 max-w-2xl text-balance text-lg leading-relaxed text-ink-muted sm:text-xl">
                {t("landing.subhead")}
              </p>

              <p className="mt-6 inline-flex items-center gap-2 rounded-full bg-surface-2 px-3.5 py-1.5 text-sm text-ink-muted">
                <Icon name="verified_user" size={16} className="text-brand" fill />
                {t("landing.trustLine")}
              </p>

              <div className="mt-10 flex flex-wrap items-center gap-3">
                <Link href="#install" className={`${ui.btnPrimary} px-6 py-3`}>
                  {t("landing.installCta")}
                  <Icon name="south" size={18} />
                </Link>
                <Link href="/onboarding" className={`${ui.btnGhost} px-6 py-3`}>
                  {t("landing.onboardingCta")}
                </Link>
              </div>

              <div className="mt-12 flex flex-wrap items-center gap-2">
                {TRUST_BADGES.map((b) => (
                  <Badge key={b} tone="neutral">
                    {b}
                  </Badge>
                ))}
              </div>
            </div>

            <div id="install" className="lg:pb-2">
              <InstallCommand />
            </div>
          </div>
        </div>
      </section>

      <section className="border-t border-border/80 bg-white">
        <div className="mx-auto max-w-6xl px-6 py-20">
          <div className="max-w-2xl">
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-brand">
              {t("landing.stepsEyebrow")}
            </p>
            <h2 className="mt-3 font-display text-3xl leading-tight tracking-[-0.02em] sm:text-4xl">
              {t("landing.stepsTitle")}
            </h2>
            <p className="mt-4 max-w-xl text-base leading-7 text-ink-muted">
              {t("landing.stepsBody")}
            </p>
          </div>

          <div className="mt-12 grid gap-8 border-t border-border pt-8 lg:grid-cols-3 lg:gap-10">
            {steps.map((step) => (
              <article key={step.id} className="space-y-3">
                <div className="text-xs font-semibold tracking-[0.22em] text-brand">{step.id}</div>
                <h3 className="font-display text-2xl leading-tight">{step.title}</h3>
                <p className="max-w-sm text-sm leading-7 text-ink-muted">{step.body}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="relative overflow-hidden border-t border-white/10 bg-[#0b0b0d] text-white">
        <div
          aria-hidden
          className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-white/25 to-transparent"
        />
        <div className="mx-auto max-w-6xl px-6 py-20">
          <div className="grid gap-10 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-white/45">
                {t("landing.featureEyebrow")}
              </p>
              <h2 className="mt-3 max-w-lg font-display text-3xl leading-tight tracking-[-0.02em] sm:text-4xl">
                {t("landing.featureTitle")}
              </h2>
              <p className="mt-4 max-w-md text-base leading-7 text-white/62">
                {t("landing.featureBody")}
              </p>
            </div>

            <div className="grid gap-6 border-t border-white/10 pt-6 sm:grid-cols-3 sm:border-t-0 sm:pt-0">
              {features.map((feature) => (
                <article key={feature.title} className="border-white/10 sm:border-l sm:pl-6">
                  <h3 className="font-display text-2xl leading-tight text-white">{feature.title}</h3>
                  <p className="mt-3 text-sm leading-7 text-white/62">{feature.body}</p>
                </article>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section className="border-t border-border bg-surface-2/65">
        <div className="mx-auto flex max-w-6xl flex-col gap-8 px-6 py-16 lg:flex-row lg:items-end lg:justify-between">
          <div className="max-w-2xl">
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-brand">
              {t("landing.finalEyebrow")}
            </p>
            <h2 className="mt-3 font-display text-3xl leading-tight tracking-[-0.02em] sm:text-4xl">
              {t("landing.finalTitle")}
            </h2>
            <p className="mt-4 text-base leading-7 text-ink-muted">{t("landing.finalBody")}</p>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <Link href="#install" className={`${ui.btnPrimary} px-6 py-3`}>
              {t("landing.installCta")}
            </Link>
            <Link href="/onboarding" className={`${ui.btnGhost} px-6 py-3`}>
              {t("landing.onboardingCta")}
            </Link>
            <Link href="/login" className={`${ui.btnGhost} px-6 py-3`}>
              {t("common.signIn")}
            </Link>
          </div>
        </div>
      </section>
    </main>
  );
}
