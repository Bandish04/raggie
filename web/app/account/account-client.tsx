// SPDX-License-Identifier: Apache-2.0

"use client";

import AccountSettings from "@/components/settings/account-settings";
import type { MemoryItem, ModelsConfig, ProfileResponse } from "@/lib/api";

/**
 * Thin wrapper kept so the standalone /account route keeps working for direct
 * URLs and deep links (#profile / #preferences / …). All of the section UI now
 * lives in <AccountSettings> (the single source of truth shared with the chat
 * settings modal); this just renders it in its "page" layout.
 */
export default function AccountClient({
  profile,
  email,
  memory = [],
  models,
}: {
  profile: ProfileResponse | null;
  email: string;
  memory?: MemoryItem[];
  models: ModelsConfig;
}) {
  return (
    <AccountSettings
      variant="page"
      profile={profile}
      email={email}
      memory={memory}
      models={models}
    />
  );
}
