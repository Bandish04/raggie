// SPDX-License-Identifier: Apache-2.0

import { getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";

import SkillsClient from "@/components/admin/skills-client";
import AdminShell from "@/components/admin/shell";
import { getModelsConfig, listAdminSkills, me } from "@/lib/api";
import { isPlatformAdmin } from "@/lib/permissions";
import { getAccessToken } from "@/lib/session";

/**
 * Skills builder. WORKSPACE_ADMIN+ (STAFF redirected; the control plane also
 * enforces). Skills are versioned execution policies invoked with a /command;
 * the edge resolves each active snapshot server-side.
 */
export default async function SkillsPage() {
  const token = await getAccessToken();
  if (!token) redirect("/login");
  const user = await me(token);
  if (!user) redirect("/login");
  if (user.role === "STAFF") redirect("/dashboard");

  // The full catalog (incl. disabled) for the builder + the allowed models for
  // the per-skill model dropdown — fetched server-side, in parallel.
  const [skills, models] = await Promise.all([
    listAdminSkills(token),
    getModelsConfig(token),
  ]);
  const t = await getTranslations("admin");

  return (
    <AdminShell
      active="skills"
      email={user.email}
      platformAdmin={isPlatformAdmin(user)}
      title={t("skillsTitle")}
      subtitle={t("skillsSubtitle")}
    >
      <SkillsClient initial={skills} models={models} />
    </AdminShell>
  );
}
