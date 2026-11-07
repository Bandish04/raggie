// SPDX-License-Identifier: Apache-2.0

import * as React from "react";

type IconProps = {
  name: string;
  size?: number;
  fill?: boolean;
  className?: string;
  weight?: number;
};

/**
 * Shared Material Symbols icon. Single source of truth for icons across the app
 * (previously re-declared inline in several components).
 */
export function Icon({ name, size = 20, fill = false, weight, className = "" }: IconProps) {
  return (
    <span
      aria-hidden="true"
      className={`material-symbols-outlined ${fill ? "fill" : ""} ${className}`}
      style={{
        fontSize: size,
        ...(weight ? { fontVariationSettings: `'FILL' ${fill ? 1 : 0}, 'wght' ${weight}` } : null),
      }}
    >
      {name}
    </span>
  );
}
