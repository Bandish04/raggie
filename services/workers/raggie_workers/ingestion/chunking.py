# SPDX-License-Identifier: Apache-2.0

"""Heading-aware chunking with overlap.

Splits on paragraph/sentence boundaries and packs whole sentences into ~1500-char
windows, carrying a word-snapped overlap into the next chunk — so a chunk never
cuts a word or sentence mid-way, and adjacent chunks share context. Boundaryless
runs (e.g. a long unbroken token) fall back to a deterministic hard split, so
the golden synthetic cases stay stable across the Python ingester and any future
Go consumer. Markdown heading ancestry is prepended to every chunk in its section,
so later spreadsheet rows or presentation notes retain their sheet/slide context.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ~1500 chars (~500 tokens for Turkish) — the practical ceiling for richer
# synthesis context without exceeding multilingual-e5-large's 512-token window
# (beyond which the embedding silently truncates a chunk's tail, hurting recall).
# The FULL chunk text is still used for synthesis. Overlap keeps boundaries shared.
DEFAULT_CHUNK_SIZE = 1500
DEFAULT_OVERLAP = 300

# Sentence ends, then any newline run — the natural seams to pack on.
_BOUNDARY = re.compile(r"(?<=[.!?…])\s+|\n+")
_HEADING = re.compile(r"^(#{1,6})\s+\S")
_NUMBERED_DETAIL_HEADING = re.compile(r"^(?:bölüm|section|chapter|part)\s+\d+\b", re.IGNORECASE)


@dataclass(frozen=True)
class DocumentChunk:
    text: str
    kind: str  # "outline" | "content"
    section_path: str = ""


def chunk_document(
    text: str, *, size: int = DEFAULT_CHUNK_SIZE, overlap: int = DEFAULT_OVERLAP
) -> list[DocumentChunk]:
    """Build retrieval chunks plus one compact document-outline chunk.

    Section-list questions need a document-level representation; otherwise each
    heading lives in a different vector and top-k may retrieve only a subset. The
    generated outline contains source headings only, never an LLM summary.
    """
    content = chunk_text(text, size=size, overlap=overlap)
    if not content:
        return []

    chunks: list[DocumentChunk] = []
    outline = _document_outline(text, size=size)
    if outline is not None:
        chunks.append(
            DocumentChunk(
                text=outline,
                kind="outline",
                section_path=_first_heading(outline),
            )
        )
    chunks.extend(
        DocumentChunk(
            text=chunk,
            kind="content",
            section_path=_leading_heading_path(chunk),
        )
        for chunk in content
    )
    return chunks


def chunk_text(
    text: str, *, size: int = DEFAULT_CHUNK_SIZE, overlap: int = DEFAULT_OVERLAP
) -> list[str]:
    if size <= 0:
        raise ValueError("size must be positive")
    if overlap < 0 or overlap >= size:
        raise ValueError("overlap must be in [0, size)")

    text = text.strip()
    if not text:
        return []

    sections = _heading_sections(text)
    if sections is None:
        return _chunk_plain(text, size=size, overlap=overlap)

    chunks: list[str] = []
    for heading, body in sections:
        if not body:
            chunks.extend(_chunk_plain(heading, size=size, overlap=overlap))
            continue
        body_size = size - len(heading) - 1  # one newline joins heading + body
        if body_size <= 0:
            chunks.extend(_chunk_plain(f"{heading}\n{body}", size=size, overlap=overlap))
            continue
        body_overlap = min(overlap, max(0, body_size - 1))
        for body_chunk in _chunk_plain(body, size=body_size, overlap=body_overlap):
            chunks.append(f"{heading}\n{body_chunk}")
    return chunks


def _chunk_plain(text: str, *, size: int, overlap: int) -> list[str]:
    segments = [s.strip() for s in _BOUNDARY.split(text) if s and s.strip()]
    chunks: list[str] = []
    cur = ""
    for seg in segments:
        if len(seg) > size:
            # A single oversized segment (no usable boundary) — flush, hard-split.
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.extend(_hard_split(seg, size, overlap))
            continue
        if not cur:
            cur = seg
        elif len(cur) + 1 + len(seg) <= size:
            cur = f"{cur} {seg}"
        else:
            chunks.append(cur)
            tail = _overlap_tail(cur, overlap)
            next_chunk = f"{tail} {seg}".strip() if tail else seg
            # Overlap is best-effort: never let it push a valid segment beyond
            # the embedding window's hard character ceiling.
            cur = next_chunk if len(next_chunk) <= size else seg
    if cur:
        chunks.append(cur)
    return chunks


def _heading_sections(text: str) -> list[tuple[str, str]] | None:
    """Return ``(heading ancestry, body)`` sections, or None when no headings exist."""
    active: dict[int, str] = {}
    sections: list[tuple[str, str]] = []
    body_lines: list[str] = []
    current_heading = ""
    saw_heading = False

    def flush(*, include_empty: bool = False) -> None:
        nonlocal body_lines
        body = "\n".join(body_lines).strip()
        if body:
            sections.append((current_heading, body))
        elif include_empty and current_heading:
            sections.append((current_heading, ""))
        body_lines = []

    for line in text.splitlines():
        # UTF-8 BOMs are common in uploaded Markdown exports. Treat a BOM-prefixed
        # first heading as a real heading so its title remains in every descendant.
        stripped = line.strip().lstrip("\ufeff")
        match = _HEADING.match(stripped)
        if match is None:
            body_lines.append(line)
            continue

        level = len(match.group(1))
        # A same-level/lower heading closes an otherwise empty section. A deeper
        # heading extends the ancestry (e.g. Slide -> Speaker notes), so no
        # redundant parent-only chunk is emitted.
        flush(include_empty=bool(active) and level <= max(active))
        for existing_level in [key for key in active if key >= level]:
            del active[existing_level]
        active[level] = stripped
        current_heading = "\n".join(active[key] for key in sorted(active))
        saw_heading = True

    flush(include_empty=True)
    if not saw_heading:
        return None

    # Preserve any preamble that appeared before the first heading.
    if sections and not sections[0][0]:
        return sections
    return sections


def _document_outline(text: str, *, size: int) -> str | None:
    headings: list[tuple[int, str]] = []
    for line in text.splitlines():
        stripped = line.strip().lstrip("\ufeff")
        match = _HEADING.match(stripped)
        if match is None:
            continue
        level = len(match.group(1))
        label = stripped[level:].strip()
        if label:
            headings.append((level, label))
    if len(headings) < 3:
        return None

    title = next((label for level, label in headings if level == 1), "")
    section_levels = [level for level, _label in headings if level > 1]
    if not section_levels:
        return None
    primary_level = min(section_levels)
    primary = [label for level, label in headings if level == primary_level]

    # Generated/synthetic documents sometimes incorrectly mark "Bölüm 1:
    # <heading> - Detay" as a sibling of the real main headings. Prefer the
    # non-numbered siblings when at least two remain; otherwise retain everything.
    non_detail = [label for label in primary if not _NUMBERED_DETAIL_HEADING.match(label)]
    if len(non_detail) >= 2:
        primary = non_detail

    deduped: list[str] = []
    seen: set[str] = set()
    for label in primary:
        key = " ".join(label.lower().split())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(label)
    if len(deduped) < 2:
        return None

    prefix = f"# {title}\n\n" if title else ""
    # Bilingual so both EN ("outline", "sections") and TR ("bölümler", "başlıklar")
    # questions match this chunk; the edge identifies it by chunk_kind, not text.
    prefix += "## Document outline (Belge bölüm dizini)\n"
    lines = [prefix.rstrip()]
    for label in deduped:
        candidate = "\n".join([*lines, f"- {label}"])
        if len(candidate) > size:
            break
        lines.append(f"- {label}")
    if len(lines) < 3:
        return None
    return "\n".join(lines)


def _first_heading(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip().lstrip("\ufeff")
        if _HEADING.match(stripped):
            return stripped
    return ""


def _leading_heading_path(text: str) -> str:
    headings: list[str] = []
    for line in text.splitlines():
        stripped = line.strip().lstrip("\ufeff")
        if not _HEADING.match(stripped):
            break
        headings.append(stripped)
    return "\n".join(headings)


def _hard_split(text: str, size: int, overlap: int) -> list[str]:
    out: list[str] = []
    start, n = 0, len(text)
    while start < n:
        end = min(start + size, n)
        out.append(text[start:end])
        if end >= n:
            break
        start = end - overlap
    return out


def _overlap_tail(text: str, overlap: int) -> str:
    if overlap <= 0:
        return ""
    if len(text) <= overlap:
        return text
    tail = text[-overlap:]
    space = tail.find(" ")  # snap to a word boundary; don't start mid-word
    return tail[space + 1 :] if 0 <= space < len(tail) - 1 else tail
