// SPDX-License-Identifier: Apache-2.0

"use client";

import Image from "next/image";
import { createContext, type ReactNode, useContext } from "react";

import type { Branding } from "@/lib/api";

const BrandingContext = createContext<Branding>({
  name: "Raggie",
  tagline: null,
  color: "#0a5bff",
  logo_data_url: null,
  icon_data_url: null,
});

export function useBranding(): Branding {
  return useContext(BrandingContext);
}

export function BrandingProvider({
  value,
  children,
}: {
  value: Branding;
  children: ReactNode;
}) {
  return <BrandingContext.Provider value={value}>{children}</BrandingContext.Provider>;
}

/** Brand logo: the uploaded image if present, else a brand-colored icon tile.
 *  `size` is the tile edge in px. */
export function BrandLogo({ size = 40, icon = "pets" }: { size?: number; icon?: string }) {
  const b = useBranding();
  const src = b.logo_data_url || b.icon_data_url;
  if (src) {
    return (
      <Image
        src={src}
        alt={b.name}
        width={size}
        height={size}
        unoptimized
        className="rounded-full object-contain"
        style={{ width: size, height: size }}
      />
    );
  }
  return (
    <span
      className="grid place-items-center rounded-full bg-brand text-brand-contrast"
      style={{ width: size, height: size }}
    >
      <span className="material-symbols-outlined fill" style={{ fontSize: size * 0.5 }}>
        {icon}
      </span>
    </span>
  );
}

/** Brand name text (white-label product name). */
export function BrandName({ className = "" }: { className?: string }) {
  const b = useBranding();
  return <span className={className}>{b.name}</span>;
}
