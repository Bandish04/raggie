// SPDX-License-Identifier: Apache-2.0

import * as React from "react";

/** Calm loading placeholder. Uses the .shimmer keyframes from globals.css. */
export function Skeleton({ className = "", ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={`shimmer rounded-xl ${className}`} {...props} />;
}
