// SPDX-License-Identifier: Apache-2.0

import type { Metadata } from "next";
import localFont from "next/font/local";
import { NextIntlClientProvider } from "next-intl";
import { getLocale, getMessages } from "next-intl/server";

import { BrandingProvider } from "@/components/branding-provider";
import { getBranding } from "@/lib/api";
import "./globals.css";

// Self-hosted type (SIL OFL 1.1, licenses next to the files in app/fonts/):
// Space Grotesk for headlines, Plus Jakarta Sans for text. Variable woff2,
// subset to Latin + Latin Extended (Turkish included). Served from this origin
// via next/font — no font CDN request at runtime, so it works air-gapped.
const displayFont = localFont({
  src: "./fonts/space-grotesk/SpaceGrotesk-Variable.woff2",
  weight: "300 700",
  display: "swap",
  variable: "--font-face-display",
});
const textFont = localFont({
  src: "./fonts/plus-jakarta-sans/PlusJakartaSans-Variable.woff2",
  weight: "200 800",
  display: "swap",
  variable: "--font-face-text",
});

/** Fallback accent — must mirror `--brand` in globals.css. */
const DEFAULT_BRAND = "#0a5bff";
/** Accept #rgb / #rrggbb (3 or 6 hex digits). */
const HEX_RE = /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/;

function safeBrandColor(color: string | null | undefined): string {
  const c = (color ?? "").trim();
  return HEX_RE.test(c) ? c : DEFAULT_BRAND;
}

/** Cheap, stable token that changes whenever the brand icon changes — appended
 *  as ?v= to the favicon URL to bust the browser's (very sticky) favicon cache
 *  on a new upload. */
function faviconVersion(dataUrl: string): string {
  const sample = `${dataUrl.length}|${dataUrl.slice(0, 128)}${dataUrl.slice(-128)}`;
  let h = 0x811c9dc5;
  for (let i = 0; i < sample.length; i += 1) {
    h ^= sample.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return (h >>> 0).toString(36);
}

export async function generateMetadata(): Promise<Metadata> {
  const branding = await getBranding();
  // The favicon is the admin's uploaded brand icon, served as a REAL image URL
  // (/branding-icon) rather than a data: URL — Chrome silently ignores data:
  // favicons and falls back to /favicon.ico, which is why uploads "didn't
  // change". The ?v= content hash busts the browser's sticky favicon cache when
  // the icon changes. Falls back to the bundled default when none is set.
  const brandIcon = branding.icon_data_url
    ? `/branding-icon?v=${faviconVersion(branding.icon_data_url)}`
    : null;
  return {
    title: branding.tagline ? `${branding.name} — ${branding.tagline}` : branding.name,
    description: branding.tagline ?? "On-premise enterprise RAG & AI chat platform",
    icons: brandIcon
      ? { icon: brandIcon, shortcut: brandIcon, apple: brandIcon }
      : {
          // Bundled Raggie mark (public/): ICO for legacy UAs, SVG + PNG for the rest.
          icon: [
            { url: "/favicon.ico", sizes: "any" },
            { url: "/icon.svg", type: "image/svg+xml" },
            { url: "/icon-192.png", type: "image/png", sizes: "192x192" },
          ],
          shortcut: "/favicon.ico",
          apple: { url: "/apple-icon.png", sizes: "180x180" },
        },
  };
}

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const [locale, messages, branding] = await Promise.all([
    getLocale(),
    getMessages(),
    getBranding(),
  ]);
  const brand = safeBrandColor(branding.color);
  // Override the hardcoded accent tokens server-side so the admin's chosen
  // color cascades through every `brand`/`accent` utility with no FOUC.
  // `--brand-strong` / `--accent` are derived so a single source color is enough.
  const brandVars = `:root{--brand:${brand};--brand-strong:color-mix(in srgb, ${brand} 78%, black);--accent:${brand};}`;
  return (
    <html lang={locale} className={`${displayFont.variable} ${textFont.variable} h-full antialiased`}>
      <head>
        {/* White-label accent — overrides the default tokens before paint. */}
        <style id="brand-vars" dangerouslySetInnerHTML={{ __html: brandVars }} />
        {/* Material Symbols (Outlined) — SELF-HOSTED (see @font-face in globals.css);
            no Google Fonts dependency so UI icons render on a closed/on-prem network. */}
      </head>
      <body className="min-h-full flex flex-col bg-bg text-ink">
        <div className="grain" aria-hidden />
        <BrandingProvider value={branding}>
          <NextIntlClientProvider messages={messages}>{children}</NextIntlClientProvider>
        </BrandingProvider>
      </body>
    </html>
  );
}
