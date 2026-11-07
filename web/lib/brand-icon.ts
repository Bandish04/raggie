// SPDX-License-Identifier: Apache-2.0

// Decodes the brand icon the control plane stores as a data: URL into raw bytes
// for /branding-icon. Only raster image types are served: an SVG on our own
// origin can run script when opened directly, so it is never returned (the
// route falls back to the default favicon instead).

const RASTER_ICON_TYPES = new Set([
  "image/png",
  "image/jpeg",
  "image/gif",
  "image/webp",
  "image/avif",
  "image/x-icon",
  "image/vnd.microsoft.icon",
]);

// data:<mime>[;params][;base64],<payload> (a data URL has no newlines, so the
// default dot — no /s flag, which needs a newer TS target — is fine).
const DATA_URL_RE = /^data:([^;,]*)((?:;[^;,]*)*),(.*)$/;

export type BrandIcon = { contentType: string; body: Buffer };

export function decodeBrandIcon(dataUrl: string): BrandIcon | null {
  const m = dataUrl.match(DATA_URL_RE);
  if (!m) return null;
  const contentType = m[1].trim().toLowerCase();
  if (!RASTER_ICON_TYPES.has(contentType)) return null;
  const isBase64 = m[2].split(";").some((p) => p.trim().toLowerCase() === "base64");
  try {
    const body = isBase64 ? Buffer.from(m[3], "base64") : Buffer.from(decodeURIComponent(m[3]), "utf-8");
    return { contentType, body };
  } catch {
    return null;
  }
}
