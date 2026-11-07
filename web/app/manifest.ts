// SPDX-License-Identifier: Apache-2.0

import type { MetadataRoute } from "next";

// Web app manifest (served at /manifest.webmanifest). Uses the bundled Raggie
// mark from public/; colors mirror --brand / --bg in globals.css.
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Raggie",
    short_name: "Raggie",
    description: "On-premise enterprise RAG & AI chat",
    start_url: "/",
    scope: "/",
    display: "standalone",
    background_color: "#ffffff",
    theme_color: "#0a5bff",
    icons: [
      { src: "/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/icon.svg", sizes: "any", type: "image/svg+xml", purpose: "any" },
    ],
  };
}
