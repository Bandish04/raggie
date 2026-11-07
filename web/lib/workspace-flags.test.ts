// SPDX-License-Identifier: Apache-2.0

import assert from "node:assert/strict";
import { test } from "node:test";

import { isWorkspaceFlag, workspaceFlagBody } from "./workspace-flags.ts";

test("builds a single-field PUT body for each flag", () => {
  assert.deepEqual(workspaceFlagBody("web_search_enabled", true), { web_search_enabled: true });
  assert.deepEqual(workspaceFlagBody("personalization_enabled", false), { personalization_enabled: false });
  assert.deepEqual(workspaceFlagBody("memory_enabled", true), { memory_enabled: true });
});

test("isWorkspaceFlag only accepts the known flags", () => {
  assert.equal(isWorkspaceFlag("memory_enabled"), true);
  assert.equal(isWorkspaceFlag("web_search_enabled"), true);
  assert.equal(isWorkspaceFlag("is_platform_admin"), false);
  assert.equal(isWorkspaceFlag(""), false);
});
