// SPDX-License-Identifier: Apache-2.0

import * as React from "react";

/**
 * A colorful, Windows/Drive-style file-type badge — a little document "image"
 * with a folded corner and a vivid, type-specific color band carrying the
 * extension label (PDF, DOCX, XLSX, MD…). Far more distinctive than a single
 * monochrome glyph: every file type reads at a glance by both color AND label.
 *
 * Pure inline SVG (no external/CDN icon set), so it renders on a closed,
 * on-prem network. Used by the Knowledge Base grid tiles and list rows.
 */

// Vivid accent per file family (Office/Drive-like). Anything unmapped falls
// back to a neutral slate so unknown types still get a clean badge.
const TYPE_COLOR: Record<string, string> = {
  pdf: "#E2483D",
  doc: "#2B7CD3",
  docx: "#2B7CD3",
  rtf: "#2B7CD3",
  xls: "#1D9D5B",
  xlsx: "#1D9D5B",
  csv: "#1D9D5B",
  ppt: "#D24726",
  pptx: "#D24726",
  md: "#7C5CFC",
  markdown: "#7C5CFC",
  txt: "#64748B",
  log: "#64748B",
  json: "#D9920B",
  xml: "#D9920B",
  yaml: "#D9920B",
  yml: "#D9920B",
  html: "#E44D26",
  htm: "#E44D26",
  png: "#DB4F8A",
  jpg: "#DB4F8A",
  jpeg: "#DB4F8A",
  gif: "#DB4F8A",
  webp: "#DB4F8A",
  svg: "#DB4F8A",
  zip: "#C99A00",
  rar: "#C99A00",
  "7z": "#C99A00",
  tar: "#C99A00",
  gz: "#C99A00",
};

const FALLBACK = "#6B7280";

export function FileGlyph({
  filename,
  className = "",
}: {
  filename: string;
  className?: string;
}) {
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";
  const color = TYPE_COLOR[ext] ?? FALLBACK;
  // The label drawn on the band — the uppercased extension, capped so a long
  // one (XLSX/PPTX/HTML) still fits; empty/no-extension files read "FILE".
  const label = (ext || "file").toUpperCase().slice(0, 4);
  const fontSize = label.length >= 4 ? 8 : label.length === 3 ? 9.5 : 11;

  return (
    <svg
      viewBox="0 0 40 48"
      className={className}
      role="img"
      aria-label={`${label} dosyası`}
      fill="none"
    >
      {/* Page body with a cut top-right corner. */}
      <path
        d="M6 2.5h20.5L34 10v33.5a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V4.5a2 2 0 0 1 2-2Z"
        fill="#ffffff"
        stroke="#E2E2E8"
        strokeWidth="1.4"
      />
      {/* Folded dog-ear. */}
      <path d="M26.5 2.5 34 10h-6a1.5 1.5 0 0 1-1.5-1.5V2.5Z" fill="#EDEDF1" />
      {/* Faint body lines, for a document feel. */}
      <g stroke="#E6E6EC" strokeWidth="1.4" strokeLinecap="round">
        <line x1="9" y1="16" x2="23" y2="16" />
        <line x1="9" y1="20.5" x2="27" y2="20.5" />
      </g>
      {/* Vivid type band + label. */}
      <rect x="7" y="28" width="24" height="13" rx="2.5" fill={color} />
      <text
        x="19"
        y="37.1"
        textAnchor="middle"
        fontFamily="ui-sans-serif, system-ui, sans-serif"
        fontSize={fontSize}
        fontWeight="700"
        letterSpacing="0.3"
        fill="#ffffff"
      >
        {label}
      </text>
    </svg>
  );
}
