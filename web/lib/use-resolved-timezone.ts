// SPDX-License-Identifier: Apache-2.0

"use client";

import { useSyncExternalStore } from "react";

import { browserTimezone, resolveTimezone } from "@/lib/timezone";

const subscribe = () => () => {};
const serverSnapshot = () => undefined;

/** The stored zone, else the browser's, else UTC. Hydration-safe: the server
 *  render and the hydrating client render both see no browser zone (stored or
 *  UTC); React then re-renders with the browser's zone. Never reads Intl on
 *  the server. */
export function useResolvedTimezone(stored: string | null | undefined): string {
  const detected = useSyncExternalStore(subscribe, browserTimezone, serverSnapshot);
  return resolveTimezone(stored, () => detected);
}
