// SPDX-License-Identifier: Apache-2.0

/** Default IANA zone when neither the user nor the browser provides one. */
export const FALLBACK_TIMEZONE = "UTC";

/** The browser's IANA zone, or undefined when Intl can't tell. Client-only:
 *  on the server this would return the server's zone, so call it from an
 *  effect (after hydration), never during a server render. */
export function browserTimezone(): string | undefined {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || undefined;
  } catch {
    return undefined;
  }
}

/** The user's stored zone, else the browser's, else UTC. */
export function resolveTimezone(
  stored: string | null | undefined,
  detect: () => string | undefined = browserTimezone,
): string {
  const own = stored?.trim();
  if (own) return own;
  try {
    return detect()?.trim() || FALLBACK_TIMEZONE;
  } catch {
    return FALLBACK_TIMEZONE;
  }
}
