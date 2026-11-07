// SPDX-License-Identifier: Apache-2.0

import { getTranslations } from "next-intl/server";

import { BrandLogo, BrandName } from "@/components/branding-provider";
import { Badge } from "@/components/ui/badge";
import { Icon } from "@/components/ui/icon";
import { invitePreview } from "@/lib/api";

import AcceptForm from "./accept-form";

export default async function AcceptPage({
  searchParams,
}: {
  searchParams: Promise<{ token?: string }>;
}) {
  const { token } = await searchParams;
  const preview = token ? await invitePreview(token) : null;
  const t = await getTranslations("accept");

  return (
    <main className="relative min-h-screen overflow-hidden bg-bg text-ink">
      <div className="spotlight" aria-hidden />

      <div className="mx-auto flex min-h-screen max-w-xl flex-col px-6 py-10">
        {!token || !preview ? (
          <div className="flex flex-1 flex-col items-center justify-center text-center">
            <div className="mb-6 flex items-center gap-2.5 font-display text-lg font-semibold">
              <BrandLogo size={30} />
              <BrandName />
            </div>
            <div className="card w-full p-8 shadow-[var(--shadow-lift)]">
              <span className="grid h-12 w-12 place-items-center rounded-full bg-danger/10 text-danger">
                <Icon name="link_off" size={24} />
              </span>
              <h1 className="mt-4 font-display text-xl font-semibold tracking-tight">
                {t("invalidTitle")}
              </h1>
              <p className="mt-2 text-sm text-ink-muted">{t("invalid")}</p>
            </div>
          </div>
        ) : (
          <div className="flex flex-1 flex-col justify-center pb-6">
            {/* Invitation hero — warm, branded, obviously an invite. */}
            <div className="animate-fade-up text-center">
              <div className="mx-auto grid h-16 w-16 place-items-center rounded-3xl bg-brand/10">
                <BrandLogo size={44} />
              </div>
              <Badge tone="brand" className="mt-5">
                <Icon name="mail" size={15} />
                {t("eyebrow")}
              </Badge>
              <h1 className="mt-4 text-balance font-display text-3xl font-semibold leading-tight tracking-tight">
                {t("welcomeTitle")}
              </h1>
              <p className="mx-auto mt-3 max-w-md text-pretty text-[15px] leading-relaxed text-ink-muted">
                {t.rich("welcomeBody", {
                  brand: () => <BrandName className="font-medium text-ink" />,
                })}
              </p>
            </div>

            <div className="card mt-8 w-full p-7 shadow-[var(--shadow-lift)] sm:p-8">
              <AcceptForm token={token} preview={preview} />
            </div>

            <p className="mt-6 text-center text-xs text-ink-muted">{t("securityNote")}</p>
          </div>
        )}
      </div>
    </main>
  );
}
