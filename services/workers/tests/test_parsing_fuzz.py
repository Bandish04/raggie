# SPDX-License-Identifier: Apache-2.0

"""Property/fuzz tests for the document parsers and the chunker.

Contract under test: whatever bytes arrive, extraction either returns text that
respects ParserLimits or raises one of the documented parse errors
(UnsupportedFormatError / InvalidDocumentError / DocumentLimitError) — never a
raw library exception (pdfminer, lxml, zipfile, KeyError, …). The chunker never
emits a chunk above its size and never raises for valid arguments.

CI runs a small, deadline-bounded profile. The ``slow`` variants (many more
examples) run nightly: ``RAGGIE_SLOW_TESTS=1 pytest -m slow tests/test_parsing_fuzz.py``.
"""

from __future__ import annotations

import io
import os
from functools import lru_cache

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from raggie_workers.ingestion.chunking import chunk_document, chunk_text
from raggie_workers.ingestion.parsing import (
    DocumentLimitError,
    InvalidDocumentError,
    ParserLimits,
    UnsupportedFormatError,
    extract_text,
)

DOCUMENTED = (UnsupportedFormatError, InvalidDocumentError, DocumentLimitError)
LIMITS = ParserLimits(max_extracted_chars=20_000, max_pdf_pages=5, max_xlsx_cells=5_000)

CI = settings(
    max_examples=25,
    deadline=3000,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)
NIGHTLY = settings(
    max_examples=400,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)
slow = pytest.mark.skipif(
    os.environ.get("RAGGIE_SLOW_TESTS") != "1", reason="nightly fuzzing (RAGGIE_SLOW_TESTS=1)"
)


# ── Seed documents (valid files the mutator starts from) ─────────────────────
@lru_cache(maxsize=1)
def _seeds() -> dict[str, bytes]:
    import docx
    import openpyxl
    import pptx
    from reportlab.pdfgen import canvas

    out: dict[str, bytes] = {}
    buf = io.BytesIO()
    pdf = canvas.Canvas(buf)
    for page in range(2):
        pdf.drawString(72, 720, f"Raggie fuzz seed page {page} with enough text to skip OCR.")
        pdf.showPage()
    pdf.save()
    out[".pdf"] = buf.getvalue()

    buf = io.BytesIO()
    document = docx.Document()
    document.add_paragraph("Raggie fuzz seed paragraph.")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "a"
    table.cell(1, 1).text = "b"
    document.save(buf)
    out[".docx"] = buf.getvalue()

    buf = io.BytesIO()
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["name", "value"])
    sheet.append(["seed", 1])
    workbook.save(buf)
    out[".xlsx"] = buf.getvalue()

    buf = io.BytesIO()
    deck = pptx.Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[1])
    slide.shapes.title.text = "Seed slide"
    slide.placeholders[1].text = "Seed body"
    deck.save(buf)
    out[".pptx"] = buf.getvalue()
    return out


FORMATS = [".pdf", ".docx", ".xlsx", ".pptx"]


@st.composite
def mutated(draw, ext: str) -> bytes:
    data = bytearray(_seeds()[ext])
    for _ in range(draw(st.integers(min_value=1, max_value=12))):
        pos = draw(st.integers(min_value=0, max_value=len(data) - 1))
        data[pos] = draw(st.integers(min_value=0, max_value=255))
    if draw(st.booleans()):
        data = data[: draw(st.integers(min_value=0, max_value=len(data)))]
    if draw(st.booleans()):
        pos = draw(st.integers(min_value=0, max_value=len(data)))
        data[pos:pos] = draw(st.binary(max_size=64))
    return bytes(data)


def _check(ext: str, data: bytes, limits: ParserLimits = LIMITS) -> None:
    try:
        text = extract_text(f"fuzz{ext}", data, limits=limits)
    except DOCUMENTED:
        return
    assert isinstance(text, str)
    assert len(text) <= limits.max_extracted_chars


def test_seeds_parse() -> None:
    for ext, data in _seeds().items():
        assert "seed" in extract_text(f"seed{ext}", data, limits=LIMITS).lower(), ext


# ── Random and mutated bytes ─────────────────────────────────────────────────
@pytest.mark.parametrize("ext", [*FORMATS, ".txt", ".md", ".bin", ""])
@CI
@given(data=st.binary(max_size=4096))
def test_random_bytes_only_raise_documented_errors(ext, data) -> None:
    _check(ext, data)


@pytest.mark.parametrize("ext", FORMATS)
@CI
@given(st.data())
def test_mutated_documents_only_raise_documented_errors(ext, data) -> None:
    _check(ext, data.draw(mutated(ext)))


@slow
@pytest.mark.slow
@pytest.mark.parametrize("ext", FORMATS)
@NIGHTLY
@given(st.data())
def test_mutated_documents_nightly(ext, data) -> None:
    _check(ext, data.draw(mutated(ext)))


# ── Size limits ──────────────────────────────────────────────────────────────
@CI
@given(text=st.text(min_size=1, max_size=5000), cap=st.integers(min_value=1, max_value=2000))
def test_text_output_never_exceeds_char_limit(text, cap) -> None:
    _check(".txt", text.encode("utf-8"), ParserLimits(max_extracted_chars=cap))


def test_pdf_page_limit_is_enforced_for_seed() -> None:
    with pytest.raises(DocumentLimitError):
        extract_text("seed.pdf", _seeds()[".pdf"], limits=ParserLimits(max_pdf_pages=1))


# ── Chunker ──────────────────────────────────────────────────────────────────
_TEXT = st.text(alphabet=st.characters(blacklist_categories=("Cs",)), max_size=6000) | st.lists(
    st.one_of(
        st.from_regex(r"#{1,6} [^\n]{0,80}", fullmatch=True),
        st.text(max_size=400),
        st.just(""),
    ),
    max_size=40,
).map("\n".join)


@CI
@given(
    text=_TEXT,
    size=st.integers(min_value=1, max_value=2000),
    data=st.data(),
)
def test_chunks_never_exceed_size(text, size, data) -> None:
    overlap = data.draw(st.integers(min_value=0, max_value=size - 1))
    chunks = chunk_text(text, size=size, overlap=overlap)
    assert all(0 < len(c) <= size for c in chunks)
    if text.strip():
        assert chunks
    for chunk in chunk_document(text, size=size, overlap=overlap):
        assert 0 < len(chunk.text) <= size


@CI
@given(size=st.integers(max_value=0), overlap=st.integers())
def test_chunker_rejects_invalid_arguments_with_value_error(size, overlap) -> None:
    with pytest.raises(ValueError):
        chunk_text("some text", size=size, overlap=overlap)


@slow
@pytest.mark.slow
@NIGHTLY
@given(text=_TEXT, size=st.integers(min_value=1, max_value=3000), data=st.data())
def test_chunks_never_exceed_size_nightly(text, size, data) -> None:
    overlap = data.draw(st.integers(min_value=0, max_value=size - 1))
    assert all(0 < len(c) <= size for c in chunk_text(text, size=size, overlap=overlap))
