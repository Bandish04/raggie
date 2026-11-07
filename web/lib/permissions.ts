// SPDX-License-Identifier: Apache-2.0

// Platform-admin (operator) authority. Distinct from an org SUPER_ADMIN: the
// control plane answers 403 to everyone else on platform-wide state (branding,
// AI config, updates, orgs, reindex-all, retry-failed, org-scoped MCP
// integrations), so the UI hides those surfaces instead of offering dead ends.

type MaybePlatformUser = { is_platform_admin?: boolean; is_active?: boolean; role?: string } | null | undefined;

export function isPlatformAdmin(user: MaybePlatformUser): boolean {
  return user?.is_platform_admin === true && user.is_active !== false;
}

/** Admin-shell sections only a platform admin can use. */
export const PLATFORM_ONLY_NAV: ReadonlySet<string> = new Set(["ai", "branding", "updates"]);

export type PlatformAdminError = "lastAdmin" | "requiresSuperAdmin" | "forbidden" | "generic";

/** Maps a failed PUT /admin/users/{id}/platform-admin to a UI message key. */
export function platformAdminError(status: number, detail: string | undefined): PlatformAdminError {
  if (status === 403) return "forbidden";
  if (status === 409) {
    const d = (detail ?? "").toLowerCase();
    if (d.includes("last platform admin")) return "lastAdmin";
    if (d.includes("super_admin")) return "requiresSuperAdmin";
  }
  return "generic";
}
