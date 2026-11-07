// SPDX-License-Identifier: Apache-2.0

import { getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";

import AdminShell from "@/components/admin/shell";
import VectorMap from "@/components/admin/vector-map";
import { getQdrantScatter, listOrgWorkspaces, me, type WorkspaceRow } from "@/lib/api";
import { isPlatformAdmin } from "@/lib/permissions";
import { getAccessToken } from "@/lib/session";

export default async function QdrantPage() {
  const token = await getAccessToken();
  if (!token) redirect("/login");
  const user = await me(token);
  if (!user) redirect("/login");
  if (user.role === "STAFF") redirect("/dashboard");

  const [scatter, workspaces] = await Promise.all([
    getQdrantScatter(token),
    user.org_id ? listOrgWorkspaces(token, user.org_id) : Promise.resolve([] as WorkspaceRow[]),
  ]);
  const t = await getTranslations("admin");
  const wsName: Record<string, string> = {};
  for (const w of workspaces) wsName[w.id] = w.name;

  return (
    <AdminShell active="qdrant" email={user.email} platformAdmin={isPlatformAdmin(user)} title={t("qdrantTitle")} subtitle={t("qdrantSubtitle")}>
      <VectorMap scatter={scatter} workspaceNames={wsName} />
    </AdminShell>
  );
}
