// SPDX-License-Identifier: Apache-2.0

// URL allowlists for rendering untrusted (model / document) markdown.
//
// Pure helpers (no DOM access) so they can be unit-tested; callers pass the
// page origin (`window.location.origin`).

// Inline raster images only: SVG can carry script/external references and is
// never needed for model output.
const DATA_IMAGE_RE = /^data:image\/(?:png|jpe?g|gif|webp|avif);/i;

const SAFE_LINK_PROTOCOLS = new Set(["http:", "https:", "mailto:"]);

/** Returns `src` when it is safe to render as an <img>: a same-origin URL
 *  (strict origin comparison after resolution, so protocol-relative
 *  `//evil.tld/?d=…` and backslash tricks are rejected) or an inline raster
 *  data image. Anything else returns null — rendering a third-party <img>
 *  would leak data to that host without a click (markdown exfiltration). */
export function safeImageSrc(src: string | undefined, origin: string): string | null {
  if (!src) return null;
  if (DATA_IMAGE_RE.test(src)) return src;
  try {
    const u = new URL(src, origin);
    if ((u.protocol === "http:" || u.protocol === "https:") && u.origin === new URL(origin).origin) {
      return src;
    }
  } catch {
    // Unparseable → reject.
  }
  return null;
}

/** Returns `href` when it is safe to render as a link: http(s), mailto, or a
 *  relative URL / fragment (which resolves against the page origin). Rejects
 *  `javascript:`, `data:`, `vbscript:`, `file:` and any other scheme, including
 *  case/whitespace-obfuscated variants (the URL parser normalises those). */
export function safeLinkHref(href: string | undefined, origin: string): string | null {
  if (!href) return null;
  try {
    return SAFE_LINK_PROTOCOLS.has(new URL(href, origin).protocol) ? href : null;
  } catch {
    return null;
  }
}

export type MarkdownImageView =
  | { kind: "img"; src: string; alt: string }
  | { kind: "link"; href: string; label: string }
  | { kind: "text"; label: string };

/** How an untrusted markdown image renders. Only a safeImageSrc-approved URL
 *  becomes an <img>; any other http(s) image is offered as a link the user must
 *  deliberately click, and an unsafe scheme is shown as inert text. This is the
 *  single source of <img> for model answers and the admin conversation viewer. */
export function markdownImageView(
  src: string | undefined,
  alt: string | undefined,
  origin: string,
): MarkdownImageView | null {
  const safe = safeImageSrc(src, origin);
  if (safe) return { kind: "img", src: safe, alt: alt ?? "" };
  const label = alt || src || "";
  const href = safeLinkHref(src, origin);
  if (href) return { kind: "link", href, label };
  return label ? { kind: "text", label } : null;
}

/** Returns `href` when it is an absolute https URL, else null. For links that
 *  come from remote data (e.g. the release manifest's url): no other scheme,
 *  no relative or protocol-relative value, no host-less "https://". */
export function safeHttpsHref(href: string | null | undefined): string | null {
  if (typeof href !== "string" || !href) return null;
  try {
    const u = new URL(href);
    return u.protocol === "https:" && u.hostname ? href : null;
  } catch {
    return null;
  }
}
