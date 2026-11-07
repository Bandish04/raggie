// SPDX-License-Identifier: Apache-2.0

import { getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";

import AiConfigClient from "@/components/admin/ai-config-client";
import EmbeddingsCard from "@/components/admin/embeddings-card";
import AdminShell from "@/components/admin/shell";
import { getAiConfig, getEmbeddingsStatus, me } from "@/lib/api";
import { isPlatformAdmin } from "@/lib/permissions";
import { getAccessToken } from "@/lib/session";

/**
 * Admin AI / model config (#16). Platform admin only (mirrors the branding page).
 * Only model SELECTION is managed here — the LLM endpoint & API key stay in the
 * edge env by design (KVKK / on-prem).
 */
export default async function AiPage() {
  const token = await getAccessToken();
  if (!token) redirect("/login");
  const user = await me(token);
  if (!user) redirect("/login");
  // Platform-wide; platform admin only (the control plane answers 403 to an
  // org SUPER_ADMIN too).
  if (!isPlatformAdmin(user)) redirect("/dashboard");

  const [config, embeddings] = await Promise.all([getAiConfig(token), getEmbeddingsStatus(token)]);
  const t = await getTranslations("admin");

  return (
    <AdminShell active="ai" email={user.email} platformAdmin={isPlatformAdmin(user)} title={t("aiTitle")} subtitle={t("aiSubtitle")}>
      <AiConfigClient initial={config} />
      <div className="mt-6">
        <EmbeddingsCard initial={embeddings} />
      </div>
    </AdminShell>
  );
}
