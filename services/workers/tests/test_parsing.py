# SPDX-License-Identifier: Apache-2.0

import io
import zipfile
from datetime import date
from pathlib import Path

import pytest

from raggie_workers.ingestion.parsing import (
    DocumentLimitError,
    InvalidDocumentError,
    ParserLimits,
    UnsupportedFormatError,
    _despace,
    extract_text,
    extract_text_from_path,
)


def test_despace_repairs_letter_spaced_lines() -> None:
    src = "M a y  2 0 2 4  –  C u r r e n t  |  I s t a n b u l ,  T u r k e y"
    out = _despace(src)
    assert "May" in out and "2024" in out and "Current" in out and "Istanbul" in out


def test_despace_leaves_normal_prose_untouched() -> None:
    prose = "I am a full-stack developer and I work at a great company."
    assert _despace(prose) == prose


def _make_pdf(pages: list[str]) -> bytes:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    for text in pages:
        c.drawString(72, 720, text)
        c.showPage()
    c.save()
    return buf.getvalue()


def _make_docx(paragraphs: list[str]) -> bytes:
    import docx

    document = docx.Document()
    for p in paragraphs:
        document.add_paragraph(p)
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


def _make_xlsx() -> bytes:
    import openpyxl

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Quarterly Revenue"
    sheet.append(["Region", "Revenue", "Report date", "Formula"])
    sheet.append(["EMEA", 125000, date(2026, 6, 1), "=B2*1.2"])
    hidden = workbook.create_sheet("Internal helper")
    hidden.sheet_state = "hidden"
    hidden.append(["Do not index this helper value"])
    buf = io.BytesIO()
    workbook.save(buf)
    workbook.close()
    return buf.getvalue()


def _make_pptx() -> bytes:
    from pptx import Presentation
    from pptx.util import Inches

    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[1])
    slide.shapes.title.text = "Enterprise Roadmap"
    slide.placeholders[1].text = "Launch target: Q4 2026"
    table_shape = slide.shapes.add_table(2, 2, Inches(1), Inches(4), Inches(6), Inches(1))
    table_shape.table.cell(0, 0).text = "Owner"
    table_shape.table.cell(0, 1).text = "Workstream"
    table_shape.table.cell(1, 0).text = "Platform"
    table_shape.table.cell(1, 1).text = "Security review"
    slide.notes_slide.notes_text_frame.text = "Customer pilot starts in September."
    buf = io.BytesIO()
    presentation.save(buf)
    return buf.getvalue()


def test_extract_pdf() -> None:
    data = _make_pdf(["Hello from page one", "Second page content"])
    text = extract_text("doc.pdf", data)
    assert "Hello from page one" in text
    assert "Second page content" in text


def test_extract_docx() -> None:
    data = _make_docx(["First paragraph", "Second paragraph"])
    text = extract_text("doc.docx", data)
    assert "First paragraph" in text
    assert "Second paragraph" in text


def test_extract_xlsx_preserves_visible_sheet_structure() -> None:
    text = extract_text("forecast.xlsx", _make_xlsx())
    assert "## Sheet: Quarterly Revenue" in text
    assert "| Region | Revenue | Report date | Formula |" in text
    assert "EMEA" in text
    assert "125000" in text
    assert "2026-06-01" in text
    assert "=B2*1.2" in text
    assert "Internal helper" not in text
    assert "Do not index" not in text


def test_extract_xlsx_from_path_matches_bytes(tmp_path: Path) -> None:
    path = tmp_path / "forecast.xlsx"
    data = _make_xlsx()
    path.write_bytes(data)
    assert extract_text_from_path(path.name, str(path)) == extract_text(path.name, data)


def test_extract_pptx_preserves_slide_table_and_notes() -> None:
    text = extract_text("roadmap.pptx", _make_pptx())
    assert "## Slide 1: Enterprise Roadmap" in text
    assert "Launch target: Q4 2026" in text
    assert "| Owner | Workstream |" in text
    assert "Platform" in text and "Security review" in text
    assert "### Speaker notes" in text
    assert "Customer pilot starts in September." in text


def test_ooxml_format_mismatch_is_rejected() -> None:
    with pytest.raises(InvalidDocumentError, match="declared office format"):
        extract_text("not-a-presentation.pptx", _make_xlsx())


def test_ooxml_compression_bomb_is_rejected() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("xl/workbook.xml", "<workbook/>")
        archive.writestr("xl/bomb.bin", b"\x00" * 100_000)
    limits = ParserLimits(max_archive_compression_ratio=2.0)
    with pytest.raises(DocumentLimitError, match="compression ratio"):
        extract_text("bomb.xlsx", buf.getvalue(), limits=limits)


def test_xlsx_cell_limit_is_enforced() -> None:
    limits = ParserLimits(max_xlsx_cells=3)
    with pytest.raises(DocumentLimitError, match="addressable cells"):
        extract_text("forecast.xlsx", _make_xlsx(), limits=limits)


def test_extract_txt() -> None:
    assert extract_text("notes.txt", b"plain text body") == "plain text body"


def test_unsupported_format_raises() -> None:
    with pytest.raises(UnsupportedFormatError):
        extract_text("archive.zip", b"PK\x03\x04")


def test_image_is_supported_via_ocr() -> None:
    # Images route to the OCR path now; with no Tesseract binary the best-effort
    # fallback yields "" rather than raising — the key is it's a handled type.
    assert isinstance(extract_text("scan.png", b"\x89PNG\r\n"), str)
