// SPDX-License-Identifier: Apache-2.0

import type { NextConfig } from "next";
import path from "node:path";
import createNextIntlPlugin from "next-intl/plugin";

const withNextIntl = createNextIntlPlugin("./i18n/request.ts");

const isDev = process.env.NODE_ENV === "development";

// Content-Security-Policy (static, nonce-less). The browser only ever talks to
// this origin — chat streams via the /api/chat proxy, never edge directly — so
// connect-src is 'self'. Exceptions, and why:
// - script-src 'unsafe-inline': the App Router inlines its RSC payload
//   (`self.__next_f.push(...)`) as inline <script>s; without per-request nonces
//   those need 'unsafe-inline'. 'unsafe-eval' is dev-only (React debugging).
// - style-src 'unsafe-inline': the server-rendered brand-color <style> in the
//   root layout and React `style={{…}}` attributes are inline styles.
// - img-src data: blob:: inline data images / local object URLs; remote images
//   are blocked, which also backs up the markdown image allowlist.
// - frame-ancestors 'none': nothing embeds the web app (the support widget is
//   served by edge and runs in the host page, not in an iframe of this app).
// upgrade-insecure-requests is deliberately omitted: on-prem installs are often
// served over plain HTTP on a LAN IP, where it would break every request.
const csp = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  // All fonts are self-hosted (app/fonts via next/font, public/fonts).
  "font-src 'self'",
  "img-src 'self' data: blob:",
  `connect-src 'self'${isDev ? " ws: wss:" : ""}`,
  "media-src 'self' blob:",
  "worker-src 'self' blob:",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

const nextConfig: NextConfig = {
  poweredByHeader: false,
  // Emit a self-contained server bundle for a slim production Docker image.
  output: "standalone",
  // Disable Next's gzip: it BUFFERS the /api/chat SSE stream (the compressor holds
  // bytes until its buffer fills, so the answer arrives all at once instead of
  // token-by-token). On-prem the uncompressed-asset cost is negligible (assets are
  // immutable + cached after first load); move compression to an ingress/CDN later
  // if WAN delivery needs it.
  compress: false,
  // Pin the tracing/workspace root to this app so an unrelated lockfile higher
  // up the filesystem cannot mis-root file tracing for the standalone output.
  outputFileTracingRoot: path.join(__dirname),
  turbopack: { root: __dirname },
  // Trim source maps from the client bundle in production.
  productionBrowserSourceMaps: false,
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "Content-Security-Policy", value: csp },
          { key: "X-Content-Type-Options", value: "nosniff" },
          // Legacy twin of frame-ancestors 'none' for older browsers.
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          // No camera/mic/location/payment/USB use anywhere in the app.
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
          },
          // HSTS is added at runtime by proxy.ts when ENABLE_HSTS=true (these
          // headers are fixed at build time, so they cannot read runtime env).
        ],
      },
      {
        // Admin-uploaded bytes served from our origin: fully inert if opened
        // directly. Listed last so it overrides the app-wide CSP above (config
        // headers also take precedence over ones a route handler sets).
        source: "/branding-icon",
        headers: [{ key: "Content-Security-Policy", value: "default-src 'none'; sandbox" }],
      },
    ];
  },
};

export default withNextIntl(nextConfig);
