# SPDX-License-Identifier: Apache-2.0

"""Bounded text extraction + normalization for uploaded documents.

The product's backbone: designed/multi-column PDFs and image/scanned PDFs must
ingest as cleanly as plain text, while office archives must not be allowed to
exhaust worker memory or CPU. Strategy, per document:
  1. PDF -> pdfplumber layout extraction (coordinate-aware: keeps multi-column
     content — e.g. a CV's "Title, Company  | dates" — coherent on one line).
  2. A page whose text layer is near-empty (image / scanned) -> OCR fallback
     (Tesseract tur+eng, page rendered via pypdfium2).
  3. Standalone images -> OCR directly.
  4. DOCX -> paragraphs + tables.
  5. XLSX -> visible sheets as labelled Markdown tables.
  6. PPTX -> labelled slides, text, tables and speaker notes.
Everything then runs through the same normalizer (repair any letter-spacing,
collapse layout whitespace). PDFs are capped by page count, OCR bitmaps by pixel
count (render scale shrinks with the page size) and images above the pixel cap
are downscaled or rejected. OOXML inputs are inspected before a parser opens
them: encrypted entries, duplicate/unsafe paths, oversized archives and extreme
compression ratios are rejected.
"""

from __future__ import annotations

import datetime as dt
import io
import math
import re
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

# A page yielding fewer real characters than this is treated as image-only and
# sent to OCR (scanned pages, infographics, image-rendered text).
OCR_MIN_CHARS = 24

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp"}
_TEXT_EXTS = {".txt", ".md"}
_OCR_LANGS = "tur+eng"
# Seconds of the parse budget kept back when OCR sets its own tesseract timeout.
_OCR_TIMEOUT_MARGIN_SECONDS = 2.0
# Default OCR render scale (~144 dpi); lowered per page so the bitmap stays under
# ParserLimits.ocr_max_pixels.
_OCR_RENDER_SCALE = 2.0
# pdfplumber's layout mode pads every page into a (width / 7.25) x (height / 13)
# character grid. A forged MediaBox (e.g. 200000 x 200000 pt) turns that into
# hundreds of millions of cells, so beyond this many cells we extract without
# layout. A0 is ~85k cells, so real documents never hit it.
_PDF_LAYOUT_MAX_CELLS = 1_000_000
_PDF_LAYOUT_X_DENSITY = 7.25
_PDF_LAYOUT_Y_DENSITY = 13.0
# A standalone image above ocr_max_pixels is downscaled before OCR; one above
# this multiple of it is rejected outright (decoding alone would be too costly).
_IMAGE_MAX_PIXELS_FACTOR = 4


_SAFE_EXTENSION = re.compile(r"[a-z0-9.]{1,16}")


def safe_extension(extension: str) -> str:
    """The extension as reported in errors: a short plain suffix, else "unknown".
    It comes from the uploaded file name, and error params reach the web UI."""
    return extension if _SAFE_EXTENSION.fullmatch(extension) else "unknown"


class UnsupportedFormatError(ValueError):
    """Raised for a file extension the ingester does not handle."""

    def __init__(self, message: str, extension: str | None = None) -> None:
        super().__init__(message)
        self.extension = extension

    def __reduce__(self):  # keep the attribute across the parser process boundary
        return (type(self), (str(self), self.extension))


def _unsupported(ext: str) -> UnsupportedFormatError:
    shown = safe_extension(ext) if ext else None
    return UnsupportedFormatError(f"unsupported file type: {shown or '<none>'}", extension=shown)


class InvalidDocumentError(ValueError):
    """Raised when a file does not match its declared document format."""


class DocumentLimitError(ValueError):
    """Raised when parser resource or output limits are exceeded. ``kind`` names
    the limit (contracts/document_errors.md) and ``limit`` its configured value."""

    def __init__(self, message: str, kind: str = "other", limit: float | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.limit = limit

    def __reduce__(self):  # keep the attributes across the parser process boundary
        return (type(self), (str(self), self.kind, self.limit))


@dataclass(frozen=True)
class ParserLimits:
    """Hard parser ceilings. Expensive limits are configurable by the worker."""

    max_archive_entries: int = 10_000
    max_archive_uncompressed_bytes: int = 256 * 1024 * 1024
    max_archive_compression_ratio: float = 100.0
    max_extracted_chars: int = 10_000_000
    max_xlsx_sheets: int = 100
    max_xlsx_rows_per_sheet: int = 100_000
    max_xlsx_columns: int = 512
    max_xlsx_cells: int = 1_000_000
    max_pptx_slides: int = 1_000
    max_pptx_shapes: int = 50_000
    max_pdf_pages: int = 1_000
    ocr_max_pixels: int = 25_000_000


_DOCUMENTED_ERRORS = (UnsupportedFormatError, InvalidDocumentError, DocumentLimitError)


@contextmanager
def _documented_errors(ext: str) -> Iterator[None]:
    """The parser boundary: hostile or corrupt input surfaces only as one of the
    documented errors, never as a raw library exception (pdfminer, lxml, zlib,
    zipfile, KeyError, …). Messages carry the exception type only — library
    messages can quote document content. Environment failures (a missing
    Tesseract binary, an unreadable path) are not the document's fault and pass
    through unchanged."""
    try:
        yield
    except _DOCUMENTED_ERRORS:
        raise
    except (FileNotFoundError, PermissionError):
        raise
    except (MemoryError, RecursionError) as exc:
        raise DocumentLimitError(
            f"{ext or 'document'} is too complex to parse", kind="complexity"
        ) from exc
    except Exception as exc:
        if type(exc).__name__ == "TesseractNotFoundError":
            raise
        label = ext.lstrip(".") or "document"
        raise InvalidDocumentError(f"could not parse {label}: {type(exc).__name__}") from exc


def extract_text(filename: str, data: bytes, *, limits: ParserLimits | None = None) -> str:
    limits = limits or ParserLimits()
    ext = Path(filename).suffix.lower()
    with _documented_errors(ext):
        return _extract_bytes(ext, data, limits)


def _extract_bytes(ext: str, data: bytes, limits: ParserLimits) -> str:
    if ext == ".pdf":
        text = _extract_pdf(data, limits)
    elif ext == ".docx":
        text = _extract_docx(data, limits)
    elif ext == ".xlsx":
        text = _extract_xlsx(data, limits)
    elif ext == ".pptx":
        text = _extract_pptx(data, limits)
    elif ext in _IMAGE_EXTS:
        text = _normalize(_ocr_image(data, limits))
    elif ext in _TEXT_EXTS:
        text = _normalize(data.decode("utf-8", errors="replace"))
    else:
        raise _unsupported(ext)
    return _enforce_output_limit(text, limits)


def extract_text_from_path(filename: str, path: str, *, limits: ParserLimits | None = None) -> str:
    """Path-based extraction for large files: every parser reads straight from
    disk so a multi-GB document is never materialised in memory. Mirrors
    extract_text exactly (same dispatch, same normalization, same errors)."""
    limits = limits or ParserLimits()
    ext = Path(filename).suffix.lower()
    with _documented_errors(ext):
        return _extract_path(ext, path, limits)


def _extract_path(ext: str, path: str, limits: ParserLimits) -> str:
    if ext == ".pdf":
        text = _extract_pdf(path, limits)
    elif ext == ".docx":
        import docx

        _validate_ooxml(path, "word/document.xml", limits)
        text = _normalize(_docx_to_text(docx.Document(path)))
    elif ext == ".xlsx":
        text = _extract_xlsx(path, limits)
    elif ext == ".pptx":
        text = _extract_pptx(path, limits)
    elif ext in _IMAGE_EXTS:
        with open(path, "rb") as fh:
            text = _normalize(_ocr_image(fh.read(), limits))
    elif ext in _TEXT_EXTS:
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = _normalize(fh.read())
    else:
        raise _unsupported(ext)
    return _enforce_output_limit(text, limits)


def _extract_pdf(source: bytes | str, limits: ParserLimits) -> str:
    """Extract a PDF from raw bytes or a file path (pdfplumber/pypdfium2 accept
    both); a path lets large PDFs be parsed without loading the file into RAM."""
    import pdfplumber

    opened = io.BytesIO(source) if isinstance(source, bytes) else source
    pages: list[str] = []
    with pdfplumber.open(opened) as pdf:
        if len(pdf.pages) > limits.max_pdf_pages:
            raise DocumentLimitError(
                f"PDF has more than {limits.max_pdf_pages} pages",
                kind="pdf_pages",
                limit=limits.max_pdf_pages,
            )
        for index, page in enumerate(pdf.pages):
            layout_cells = (float(page.width) / _PDF_LAYOUT_X_DENSITY) * (
                float(page.height) / _PDF_LAYOUT_Y_DENSITY
            )
            text = page.extract_text(layout=layout_cells <= _PDF_LAYOUT_MAX_CELLS) or ""
            if len(text.strip()) < OCR_MIN_CHARS:
                ocr = _ocr_pdf_page(source, index, limits)
                if len(ocr.strip()) > len(text.strip()):
                    text = ocr
            pages.append(text)
    return _normalize(_despace("\n".join(pages)))


def _ocr_render_scale(width_pt: float, height_pt: float, max_pixels: int) -> float:
    """Largest render scale (<= the default) whose bitmap fits in max_pixels.
    0.0 for a degenerate page that cannot be rendered."""
    area = width_pt * height_pt
    if width_pt <= 0 or height_pt <= 0 or max_pixels <= 0:
        return 0.0
    return min(_OCR_RENDER_SCALE, math.sqrt(max_pixels / area))


def _ocr_timeout() -> float:
    """pytesseract timeout: the parse budget left in this parser child, minus a
    margin so tesseract stops (and OCR degrades to "") before the parent kills
    the whole process group. 0 (no limit) when called outside a parser child."""
    from raggie_workers.ingestion.isolation import remaining_budget

    budget = remaining_budget()
    if budget is None:
        return 0
    return max(1.0, budget - _OCR_TIMEOUT_MARGIN_SECONDS)


def _ocr_pdf_page(source: bytes | str, index: int, limits: ParserLimits) -> str:
    """Render one PDF page to a bitmap and OCR it. Best-effort: any failure
    (missing Tesseract, render error) yields "" so text extraction still wins.
    `source` is the PDF bytes or a file path (pypdfium2 accepts either). The
    render scale is derived from the page size so a huge MediaBox cannot
    allocate a multi-gigapixel bitmap."""
    try:
        import pypdfium2 as pdfium
        import pytesseract

        doc = pdfium.PdfDocument(source)
        try:
            page = doc[index]
            width, height = page.get_size()
            scale = _ocr_render_scale(width, height, limits.ocr_max_pixels)
            if width * scale < 1 or height * scale < 1:
                return ""
            pil = page.render(scale=scale).to_pil()
            return pytesseract.image_to_string(pil, lang=_OCR_LANGS, timeout=_ocr_timeout())
        finally:
            doc.close()
    except Exception:  # noqa: BLE001 — OCR is a best-effort fallback
        return ""


def _ocr_image(data: bytes, limits: ParserLimits) -> str:
    try:
        import pytesseract
        from PIL import Image
    except Exception:  # noqa: BLE001 — best-effort
        return ""
    try:
        image = Image.open(io.BytesIO(data))  # lazy: reads the header only
    except Exception:  # noqa: BLE001 — unreadable image → nothing to OCR
        return ""
    width, height = image.size
    if width * height > limits.ocr_max_pixels * _IMAGE_MAX_PIXELS_FACTOR:
        raise DocumentLimitError(
            f"image is {width}x{height}; more than "
            f"{limits.ocr_max_pixels * _IMAGE_MAX_PIXELS_FACTOR} pixels",
            kind="image_pixels",
            limit=limits.ocr_max_pixels * _IMAGE_MAX_PIXELS_FACTOR,
        )
    try:
        if width * height > limits.ocr_max_pixels:
            ratio = math.sqrt(limits.ocr_max_pixels / (width * height))
            image.thumbnail((max(1, int(width * ratio)), max(1, int(height * ratio))))
        return pytesseract.image_to_string(image, lang=_OCR_LANGS, timeout=_ocr_timeout())
    except Exception:  # noqa: BLE001 — best-effort
        return ""


def _extract_docx(data: bytes, limits: ParserLimits) -> str:
    import docx  # python-docx

    _validate_ooxml(data, "word/document.xml", limits)
    return _normalize(_docx_to_text(docx.Document(io.BytesIO(data))))


def _docx_to_text(document: object) -> str:
    """Paragraphs + tables of an opened python-docx Document → flat text.
    Shared by the bytes and path entry points (docx.Document accepts both)."""
    parts = [p.text for p in document.paragraphs]
    for table in document.tables:  # tables hold structured facts; keep them
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            if any(cells):
                parts.append(" | ".join(cells))
    return "\n".join(parts)


class _TextAccumulator:
    """Build structured parser output without exceeding the configured ceiling."""

    def __init__(self, max_chars: int) -> None:
        self._max_chars = max_chars
        self._chars = 0
        self._parts: list[str] = []

    def append(self, value: str) -> None:
        value = value.strip()
        if not value:
            return
        added = len(value) + (2 if self._parts else 0)
        if self._chars + added > self._max_chars:
            raise DocumentLimitError(
                f"extracted text exceeds {self._max_chars} characters",
                kind="extracted_chars",
                limit=self._max_chars,
            )
        self._parts.append(value)
        self._chars += added

    def render(self) -> str:
        return _normalize("\n\n".join(self._parts))


def _validate_ooxml(source: bytes | str, required_member: str, limits: ParserLimits) -> None:
    """Inspect the ZIP central directory before an OOXML parser decompresses it."""
    opened: io.BytesIO | str = io.BytesIO(source) if isinstance(source, bytes) else source
    try:
        with zipfile.ZipFile(opened) as archive:
            infos = archive.infolist()
            if len(infos) > limits.max_archive_entries:
                raise DocumentLimitError(
                    f"office archive has more than {limits.max_archive_entries} entries",
                    kind="archive_entries",
                    limit=limits.max_archive_entries,
                )

            names: set[str] = set()
            total_compressed = 0
            total_uncompressed = 0
            for info in infos:
                path = PurePosixPath(info.filename)
                if info.filename.startswith("/") or "\\" in info.filename or ".." in path.parts:
                    raise InvalidDocumentError("office archive contains an unsafe path")
                if info.filename in names:
                    raise InvalidDocumentError("office archive contains duplicate entries")
                names.add(info.filename)
                if info.flag_bits & 0x1:
                    raise InvalidDocumentError("encrypted office archives are unsupported")
                if info.is_dir():
                    continue

                total_compressed += info.compress_size
                total_uncompressed += info.file_size
                if total_uncompressed > limits.max_archive_uncompressed_bytes:
                    raise DocumentLimitError(
                        "office archive uncompressed size exceeds "
                        f"{limits.max_archive_uncompressed_bytes} bytes",
                        kind="archive_uncompressed_bytes",
                        limit=limits.max_archive_uncompressed_bytes,
                    )
                if (
                    info.file_size > 0
                    and info.file_size / max(1, info.compress_size)
                    > limits.max_archive_compression_ratio
                ):
                    raise DocumentLimitError(
                        "office archive compression ratio is unsafe",
                        kind="archive_compression_ratio",
                        limit=limits.max_archive_compression_ratio,
                    )

            if (
                total_uncompressed > 0
                and total_uncompressed / max(1, total_compressed)
                > limits.max_archive_compression_ratio
            ):
                raise DocumentLimitError(
                    "office archive compression ratio is unsafe",
                    kind="archive_compression_ratio",
                    limit=limits.max_archive_compression_ratio,
                )
            if required_member not in names or "[Content_Types].xml" not in names:
                raise InvalidDocumentError("file does not match its declared office format")
    except zipfile.BadZipFile as exc:
        raise InvalidDocumentError("invalid office archive") from exc


def _xlsx_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip().replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _extract_xlsx(source: bytes | str, limits: ParserLimits) -> str:
    import openpyxl

    _validate_ooxml(source, "xl/workbook.xml", limits)
    opened: io.BytesIO | str = io.BytesIO(source) if isinstance(source, bytes) else source
    workbook = openpyxl.load_workbook(
        opened,
        read_only=True,
        data_only=False,
        keep_links=False,
    )
    output = _TextAccumulator(limits.max_extracted_chars)
    total_cells = 0
    try:
        if len(workbook.worksheets) > limits.max_xlsx_sheets:
            raise DocumentLimitError(
                f"workbook has more than {limits.max_xlsx_sheets} sheets",
                kind="xlsx_sheets",
                limit=limits.max_xlsx_sheets,
            )
        for sheet in workbook.worksheets:
            # Hidden sheets frequently contain helper data that users did not intend
            # to publish through search. Only the visible workbook surface is indexed.
            if sheet.sheet_state != "visible":
                continue
            if sheet.max_row > limits.max_xlsx_rows_per_sheet:
                raise DocumentLimitError(
                    f"sheet {sheet.title!r} exceeds {limits.max_xlsx_rows_per_sheet} rows",
                    kind="xlsx_rows",
                    limit=limits.max_xlsx_rows_per_sheet,
                )
            if sheet.max_column > limits.max_xlsx_columns:
                raise DocumentLimitError(
                    f"sheet {sheet.title!r} exceeds {limits.max_xlsx_columns} columns",
                    kind="xlsx_columns",
                    limit=limits.max_xlsx_columns,
                )
            estimated_cells = sheet.max_row * sheet.max_column
            total_cells += estimated_cells
            if total_cells > limits.max_xlsx_cells:
                raise DocumentLimitError(
                    f"workbook exceeds {limits.max_xlsx_cells} addressable cells",
                    kind="xlsx_cells",
                    limit=limits.max_xlsx_cells,
                )

            output.append(f"## Sheet: {sheet.title}")
            wrote_header = False
            for row in sheet.iter_rows():
                cells = [_xlsx_value(cell.value) for cell in row]
                while cells and not cells[-1]:
                    cells.pop()
                if not cells or not any(cells):
                    continue
                output.append("| " + " | ".join(cells) + " |")
                if not wrote_header:
                    output.append("| " + " | ".join(["---"] * len(cells)) + " |")
                    wrote_header = True
    finally:
        workbook.close()
    return output.render()


def _shape_texts(shape: Any, counter: list[int], limits: ParserLimits) -> list[str]:
    counter[0] += 1
    if counter[0] > limits.max_pptx_shapes:
        raise DocumentLimitError(
            f"presentation exceeds {limits.max_pptx_shapes} shapes",
            kind="pptx_shapes",
            limit=limits.max_pptx_shapes,
        )
    if getattr(shape, "has_table", False):
        rows = [[cell.text for cell in row.cells] for row in shape.table.rows]
        table = _table_to_markdown(rows)
        return [table] if table else []
    if hasattr(shape, "shapes"):
        nested: list[str] = []
        for child in shape.shapes:
            nested.extend(_shape_texts(child, counter, limits))
        return nested
    if getattr(shape, "has_text_frame", False):
        text = shape.text.strip()
        return [text] if text else []
    return []


def _extract_pptx(source: bytes | str, limits: ParserLimits) -> str:
    from pptx import Presentation

    _validate_ooxml(source, "ppt/presentation.xml", limits)
    opened: io.BytesIO | str = io.BytesIO(source) if isinstance(source, bytes) else source
    presentation = Presentation(opened)
    if len(presentation.slides) > limits.max_pptx_slides:
        raise DocumentLimitError(
            f"presentation has more than {limits.max_pptx_slides} slides",
            kind="pptx_slides",
            limit=limits.max_pptx_slides,
        )

    output = _TextAccumulator(limits.max_extracted_chars)
    shape_counter = [0]
    for index, slide in enumerate(presentation.slides, start=1):
        title_shape = slide.shapes.title
        title = title_shape.text.strip() if title_shape is not None else ""
        heading = f"## Slide {index}"
        if title:
            heading += f": {title}"
        output.append(heading)

        shapes = sorted(
            slide.shapes,
            key=lambda shape: (
                int(getattr(shape, "top", 0)),
                int(getattr(shape, "left", 0)),
            ),
        )
        for shape in shapes:
            if title_shape is not None and shape == title_shape:
                shape_counter[0] += 1
                continue
            for text in _shape_texts(shape, shape_counter, limits):
                output.append(text)

        try:
            notes = slide.notes_slide.notes_text_frame.text.strip()
        except (AttributeError, ValueError):
            notes = ""
        if notes:
            output.append(f"### Speaker notes\n{notes}")
    return output.render()


def _enforce_output_limit(text: str, limits: ParserLimits) -> str:
    if len(text) > limits.max_extracted_chars:
        raise DocumentLimitError(
            f"extracted text exceeds {limits.max_extracted_chars} characters",
            kind="extracted_chars",
            limit=limits.max_extracted_chars,
        )
    return text


# Styled headers/dates in some PDFs extract with a space between every glyph —
# "C u r r e n t". pdfplumber's layout mode avoids most of this, but repair any
# residual: only lines that are *predominantly* single-character tokens, so
# normal prose (single-letter words like "a"/"I" are rare) is left untouched.
def _despace(text: str) -> str:
    out: list[str] = []
    for line in text.split("\n"):
        tokens = [t for t in line.split(" ") if t]
        singles = sum(1 for t in tokens if len(t) == 1)
        if len(tokens) >= 4 and singles / len(tokens) > 0.6:
            joined = re.sub(r"(?<=\S) (?=\S)", "", line)
            line = re.sub(r"\s{2,}", " ", joined).strip()
        out.append(line)
    return "\n".join(out)


def _table_to_markdown(rows: list[list[str]]) -> str:
    """Render a table (rows of cell strings) as a GFM markdown table; the first
    non-empty row is the header. Pure function (no docx dep) so it's unit-testable.
    Pipe and newline characters in cells are escaped/flattened."""
    cleaned = [[c.strip().replace("|", "\\|").replace("\n", " ") for c in row] for row in rows]
    cleaned = [r for r in cleaned if any(c for c in r)]
    if not cleaned:
        return ""
    width = max(len(r) for r in cleaned)
    cleaned = [r + [""] * (width - len(r)) for r in cleaned]
    lines = [
        "| " + " | ".join(cleaned[0]) + " |",
        "| " + " | ".join(["---"] * width) + " |",
    ]
    for r in cleaned[1:]:
        lines.append("| " + " | ".join(r) + " |")
    return "\n".join(lines)


def _normalize(text: str) -> str:
    text = re.sub(r"[ \t]{2,}", " ", text)  # collapse aligned-layout space runs
    text = re.sub(r"\n[ \t]+", "\n", text)  # strip leading indentation
    text = re.sub(r"\n{3,}", "\n\n", text)  # collapse big vertical gaps
    return text.strip()
