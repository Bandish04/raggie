// SPDX-License-Identifier: Apache-2.0

// POST /auth/memory/import failures → the account page message.
export type MemoryImportError = "empty" | "tooLong" | "disabled" | "generic";

export function memoryImportError(status: number): Exclude<MemoryImportError, "empty"> {
  // 400: empty after server-side validation, or over the length limit.
  if (status === 400) return "tooLong";
  // 404 "memory is not enabled": MEMORY_ENABLED=false platform-wide.
  if (status === 404) return "disabled";
  return "generic";
}
