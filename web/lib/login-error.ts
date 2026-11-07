// SPDX-License-Identifier: Apache-2.0

// Maps a failed control-plane /auth/login response to what the sign-in form
// shows. 429 covers both the per-account progressive lockout and the per-IP
// auth rate limit; the control plane sends Retry-After in seconds.

export type LoginError =
  | { error: "invalid" }
  | { error: "locked"; retryAfterMinutes?: number }
  | { error: "unavailable" };

export function loginErrorFromResponse(status: number, retryAfter: string | null): LoginError {
  if (status === 429) {
    const seconds = Number(retryAfter);
    return Number.isFinite(seconds) && seconds > 0
      ? { error: "locked", retryAfterMinutes: Math.ceil(seconds / 60) }
      : { error: "locked" };
  }
  if (status === 0 || status >= 500) return { error: "unavailable" };
  return { error: "invalid" };
}
