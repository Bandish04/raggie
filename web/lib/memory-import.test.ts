// SPDX-License-Identifier: Apache-2.0

import assert from "node:assert/strict";
import { test } from "node:test";

import { memoryImportError } from "./memory-import.ts";

test("maps import failures to the account page messages", () => {
  assert.equal(memoryImportError(400), "tooLong");
  // Memory is switched off platform-wide (MEMORY_ENABLED=false).
  assert.equal(memoryImportError(404), "disabled");
  assert.equal(memoryImportError(500), "generic");
  assert.equal(memoryImportError(0), "generic");
});
