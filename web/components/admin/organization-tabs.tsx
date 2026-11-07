// SPDX-License-Identifier: Apache-2.0

"use client";

import { useTranslations } from "next-intl";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useState } from "react";

import DirectoryClient from "@/components/admin/directory-client";
import OrgChart from "@/components/admin/org-chart";
import TeamsPanel from "@/components/admin/teams-panel";
import UserManager from "@/components/admin/user-manager";
import { Icon } from "@/components/ui/icon";
import type { Department, Location, OrgChartNode, OrgUser, TeamRow } from "@/lib/api";

export type OrgTab = "people" | "teams" | "directory" | "org-chart";

const TABS: { key: OrgTab; icon: string; label: "orgTabPeople" | "orgTabTeams" | "orgTabDirectory" | "orgTabOrgChart" }[] = [
  { key: "people", icon: "manage_accounts", label: "orgTabPeople" },
  { key: "teams", icon: "groups", label: "orgTabTeams" },
  { key: "directory", icon: "apartment", label: "orgTabDirectory" },
  { key: "org-chart", icon: "account_tree", label: "orgTabOrgChart" },
];

type Props = {
  initialTab: OrgTab;
  users: OrgUser[];
  departments: Department[];
  locations: Location[];
  teams: TeamRow[];
  orgChart: OrgChartNode[];
  canManageSuperAdmin: boolean;
  canManagePlatformAdmin: boolean;
};

/**
 * Consolidated Organization surface. Four former top-level admin pages (People,
 * Teams, Directory, Org chart) are reused verbatim as the four tab bodies. The
 * active tab is reflected in the `?tab=` query param so each is deep-linkable
 * and the old routes can redirect straight to the right tab.
 */
export default function OrganizationTabs({
  initialTab,
  users,
  departments,
  locations,
  teams,
  orgChart,
  canManageSuperAdmin,
  canManagePlatformAdmin,
}: Props) {
  const t = useTranslations("admin");
  const router = useRouter();
  const pathname = usePathname();
  const search = useSearchParams();
  const [tab, setTab] = useState<OrgTab>(initialTab);

  // Reflect the selection in the URL without a full navigation so deep links
  // (and the old-route redirects) resolve to the right tab and stay shareable.
  const select = useCallback(
    (next: OrgTab) => {
      setTab(next);
      const params = new URLSearchParams(search.toString());
      params.set("tab", next);
      router.replace(`${pathname}?${params.toString()}`, { scroll: false });
    },
    [pathname, router, search],
  );

  return (
    <div className="space-y-6">
      <div
        role="tablist"
        aria-label={t("organizationTitle")}
        className="flex flex-wrap gap-1 rounded-2xl border border-border bg-surface-2/60 p-1"
      >
        {TABS.map((item) => {
          const on = item.key === tab;
          return (
            <button
              key={item.key}
              role="tab"
              type="button"
              id={`org-tab-${item.key}`}
              aria-selected={on}
              aria-controls={`org-panel-${item.key}`}
              onClick={() => select(item.key)}
              className={`inline-flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-medium transition ${
                on
                  ? "bg-surface text-ink shadow-[var(--shadow-soft)]"
                  : "text-ink-muted hover:bg-surface/60 hover:text-ink"
              }`}
            >
              <Icon name={item.icon} size={18} />
              {t(item.label)}
            </button>
          );
        })}
      </div>

      <div
        role="tabpanel"
        id={`org-panel-${tab}`}
        aria-labelledby={`org-tab-${tab}`}
        tabIndex={0}
        className="outline-none"
      >
        {tab === "people" && (
          <UserManager
            users={users}
            departments={departments}
            locations={locations}
            canManageSuperAdmin={canManageSuperAdmin}
            canManagePlatformAdmin={canManagePlatformAdmin}
          />
        )}
        {tab === "teams" && <TeamsPanel teams={teams} />}
        {tab === "directory" && (
          <DirectoryClient departments={departments} locations={locations} users={users} />
        )}
        {tab === "org-chart" && <OrgChart nodes={orgChart} />}
      </div>
    </div>
  );
}
