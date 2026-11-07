// SPDX-License-Identifier: Apache-2.0

import { getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";

import AdminShell from "@/components/admin/shell";
import ConversationsClient from "@/components/admin/conversations-client";
import { me } from "@/lib/api";
import { isPlatformAdmin } from "@/lib/permissions";
import { getAccessToken } from "@/lib/session";

export default async function AdminConversationsPage() {
  const token = await getAccessToken();
  if (!token) redirect("/login");
  const user = await me(token);
  if (!user) redirect("/login");
  // Defense in depth: the edge also 403s STAFF; keep them out of the page too.
  if (user.role === "STAFF") redirect("/dashboard");

  const t = await getTranslations("admin");
  return (
    <AdminShell
      active="conversations"
      email={user.email}
      platformAdmin={isPlatformAdmin(user)}
      title={t("conversationsTitle")}
      subtitle={t("conversationsSubtitle")}
    >
      <ConversationsClient />
    </AdminShell>
  );
}
