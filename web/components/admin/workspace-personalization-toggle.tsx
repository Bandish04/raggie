// SPDX-License-Identifier: Apache-2.0

"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { setWorkspaceFlagAction } from "@/app/admin/workspaces/actions";
import type { WorkspaceFlag } from "@/lib/workspace-flags";

// A small switch for a per-workspace chat-intelligence flag (personalization,
// web search or memory). Optimistic with revert-on-failure. `disabled` locks it
// when the feature is off platform-wide (title explains why).
export default function WorkspaceFlagToggle({
  workspaceId,
  field,
  enabled,
  title,
  disabled = false,
}: {
  workspaceId: string;
  field: WorkspaceFlag;
  enabled: boolean;
  title?: string;
  disabled?: boolean;
}) {
  const [on, setOn] = useState(enabled);
  const [pending, start] = useTransition();
  const router = useRouter();

  function toggle() {
    const next = !on;
    setOn(next); // optimistic
    start(async () => {
      const ok = await setWorkspaceFlagAction(workspaceId, field, next);
      if (!ok) setOn(!next); // revert on failure
      router.refresh();
    });
  }

  return (
    <button
      type="button"
      onClick={toggle}
      disabled={pending || disabled}
      role="switch"
      aria-checked={on}
      aria-label={title}
      title={title}
      className={`relative inline-flex h-6 w-11 items-center rounded-full transition ${
        on ? "bg-brand" : "bg-surface-3"
      } ${pending || disabled ? "opacity-60" : ""} ${disabled ? "cursor-not-allowed" : ""}`}
    >
      <span
        className={`inline-block h-4 w-4 transform rounded-full bg-white transition ${
          on ? "translate-x-6" : "translate-x-1"
        }`}
      />
    </button>
  );
}
