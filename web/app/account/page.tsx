// SPDX-License-Identifier: Apache-2.0

import Link from "next/link";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { signOutAction } from "@/app/actions/auth";
import { BrandLogo, BrandName } from "@/components/branding-provider";
import { Icon } from "@/components/ui/icon";
import { getModelsConfig, getProfile, listMyMemory, me } from "@/lib/api";
import { getAccessToken } from "@/lib/session";

import AccountClient from "./account-client";

export default async function AccountPage() {
  const token = await getAccessToken();
  if (!token) redirect("/login");
  const profile = await me(token);
  if (!profile) redirect("/login");
  const [data, memory, models] = await Promise.all([
    getProfile(token),
    listMyMemory(token),
    getModelsConfig(token),
  ]);
  const t = await getTranslations("account");
  const tc = await getTranslations("common");

  return (
    <div className="min-h-screen bg-bg text-ink">
      <header className="sticky top-0 z-30 flex h-16 items-center justify-between border-b border-border bg-surface/80 px-6 backdrop-blur">
        <Link href="/dashboard" className="flex items-center gap-2.5 font-display text-lg font-semibold">
          <BrandLogo size={30} />
          <BrandName />
        </Link>
        <form action={signOutAction}>
          <button
            type="submit"
            className="inline-flex items-center gap-1.5 rounded-full px-3 py-2 text-sm font-medium text-ink-muted transition-colors hover:bg-surface-2 hover:text-ink"
          >
            <Icon name="logout" size={20} />
            <span className="hidden sm:inline">{tc("signOut")}</span>
          </button>
        </form>
      </header>

      <main className="mx-auto w-full max-w-4xl px-6 py-12 sm:py-16">
        <div className="flex flex-col gap-1.5">
          <p className="text-xs font-semibold uppercase tracking-wider text-brand">
            {t("eyebrow")}
          </p>
          <h1 className="font-display text-2xl font-semibold tracking-tight sm:text-3xl">
            {t("title")}
          </h1>
          <p className="max-w-2xl text-sm leading-relaxed text-ink-muted">{t("subtitle")}</p>
        </div>

        <div className="mt-12">
          <AccountClient
            profile={data}
            email={profile.email}
            memory={memory}
            models={models}
          />
        </div>
      </main>
    </div>
  );
}
