# SPDX-License-Identifier: Apache-2.0

"""Document model for the synthetic sample corpus.

Content modules (scripts/corpus/content/*.py) describe each document once with
these plain dataclasses; build.py renders them to PDF/DOCX/XLSX/PPTX/MD/TXT/PNG.
Text is written as plain strings (no inline markup) so every renderer emits it
verbatim and golden-set evidence quotes match the extracted text.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import PurePosixPath


@dataclass(frozen=True)
class H:
    """Heading. level 1 = section, 2 = subsection, 3 = minor heading."""

    text: str
    level: int = 1


@dataclass(frozen=True)
class P:
    text: str


@dataclass(frozen=True)
class Bullets:
    items: tuple[str, ...]
    numbered: bool = False


@dataclass(frozen=True)
class Table:
    header: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    caption: str = ""
    # Relative column widths for PDF/DOCX (optional; defaults to equal widths).
    widths: tuple[float, ...] = ()


@dataclass(frozen=True)
class PageBreak:
    pass


Block = H | P | Bullets | Table | PageBreak


@dataclass(frozen=True)
class Sheet:
    """One worksheet. `header` is the column header row; `rows` hold cell
    values (str / int / float). Keep cells the questions target as literal
    values — the worker reads raw cell values, never formula results."""

    name: str
    header: tuple[str, ...]
    rows: tuple[tuple[object, ...], ...]
    title: str = ""  # optional title line above the header
    notes: tuple[str, ...] = ()  # optional lines below the table
    widths: tuple[int, ...] = ()  # column widths in characters (optional)


@dataclass(frozen=True)
class Slide:
    title: str
    bullets: tuple[str, ...] = ()
    table: Table | None = None
    notes: str = ""
    subtitle: str = ""  # used on the title slide only


@dataclass
class Doc:
    """One corpus document. `path` is relative to the corpus root
    (<department-folder>/<FileName>.<ext>); the extension picks the renderer."""

    path: str
    title: str
    lang: str  # "tr" | "en"
    date: dt.date  # issue date; also used as the file's fixed creation date
    doc_no: str = ""
    subtitle: str = ""
    classification: str = ""  # defaults per language (see label())
    meta: tuple[tuple[str, str], ...] = ()  # key/value lines under the title
    blocks: tuple[Block, ...] = ()
    sheets: tuple[Sheet, ...] = ()
    slides: tuple[Slide, ...] = ()
    extra: dict = field(default_factory=dict)

    @property
    def name(self) -> str:
        return PurePosixPath(self.path).name

    @property
    def folder(self) -> str:
        return PurePosixPath(self.path).parts[0]

    @property
    def ext(self) -> str:
        return PurePosixPath(self.path).suffix.lower()

    def label(self) -> str:
        if self.classification:
            return self.classification
        return "Şirket İçi" if self.lang == "tr" else "Internal"


# ── Authoring helpers (keep content modules terse) ───────────────────────────
def H1(text: str) -> H:
    return H(text, 1)


def H2(text: str) -> H:
    return H(text, 2)


def H3(text: str) -> H:
    return H(text, 3)


def UL(*items: str) -> Bullets:
    return Bullets(tuple(items))


def OL(*items: str) -> Bullets:
    return Bullets(tuple(items), numbered=True)


def T(header, rows, caption: str = "", widths=()) -> Table:
    return Table(tuple(header), tuple(tuple(r) for r in rows), caption, tuple(widths))


def D(year: int, month: int, day: int) -> dt.date:
    return dt.date(year, month, day)
