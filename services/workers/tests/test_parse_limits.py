# SPDX-License-Identifier: Apache-2.0

"""Parser resource ceilings: hostile PDFs, images and archives must fail fast
with a clear reason instead of exhausting the worker's memory or CPU."""

import io
import math
import os
import time
import zipfile
from pathlib import Path
from uuid import uuid4

import parse_helpers  # tests/ is on sys.path (rootdir conftest); the child re-imports it
import pytest

import raggie_workers.ingestion.pipeline as pipeline_module
from raggie_workers.ingestion.embedder import DeterministicMockEmbedder
from raggie_workers.ingestion.isolation import ParserCrashedError, run_isolated
from raggie_workers.ingestion.parsing import (
    DocumentLimitError,
    ParserLimits,
    extract_text,
    extract_text_from_path,
)
from raggie_workers.ingestion.pipeline import DocumentJob, process_document


def _make_pdf(pages: list[str], pagesize=(612, 792)) -> bytes:
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=pagesize)
    for page in pages:
        if page:
            c.drawString(54, 200, page)
        c.showPage()
    c.save()
    return buf.getvalue()


def _png(size: tuple[int, int]) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("L", size, color=255).save(buf, format="PNG")
    return buf.getvalue()


# ─────────────────────────────────── PDF ───────────────────────────────────


def test_pdf_page_cap_is_enforced() -> None:
    data = _make_pdf([f"Page {i} has enough text to skip the OCR fallback." for i in range(5)])
    with pytest.raises(DocumentLimitError, match="more than 3 pages"):
        extract_text("big.pdf", data, limits=ParserLimits(max_pdf_pages=3))


def test_pdf_under_page_cap_still_parses() -> None:
    data = _make_pdf(["Exactly three pages is allowed by the page ceiling."] * 3)
    text = extract_text("ok.pdf", data, limits=ParserLimits(max_pdf_pages=3))
    assert "three pages is allowed" in text


def test_ocr_render_of_huge_mediabox_respects_pixel_cap(monkeypatch) -> None:
    import pypdfium2 as pdfium

    width = height = 20_000.0  # points; at the old fixed scale=2.0 → 1.6 GPx bitmap
    data = _make_pdf([""], pagesize=(width, height))  # empty page → OCR fallback
    scales: list[float] = []

    def fake_render(self, *args, scale=1, **kwargs):
        scales.append(scale)
        raise RuntimeError("render stubbed out")  # never allocate in the test

    monkeypatch.setattr(pdfium.PdfPage, "render", fake_render)
    limit = 25_000_000
    extract_text("poster.pdf", data, limits=ParserLimits(ocr_max_pixels=limit))

    assert scales, "OCR fallback should have tried to render the empty page"
    assert (width * scales[0]) * (height * scales[0]) <= limit


def test_ocr_render_keeps_full_quality_for_normal_pages(monkeypatch) -> None:
    import pypdfium2 as pdfium

    data = _make_pdf([""])  # US letter, empty → OCR
    scales: list[float] = []

    def fake_render(self, *args, scale=1, **kwargs):
        scales.append(scale)
        raise RuntimeError("render stubbed out")

    monkeypatch.setattr(pdfium.PdfPage, "render", fake_render)
    extract_text("scan.pdf", data)
    assert scales == [2.0]


def test_huge_mediabox_does_not_build_layout_text_grid(monkeypatch) -> None:
    import pdfplumber.page

    # pdfplumber's layout mode pads a (width/7.25) x (height/13) character grid:
    # ~420M cells for this page. It must fall back to plain extraction.
    data = _make_pdf(
        ["A poster sized page with a perfectly ordinary sentence on it."],
        pagesize=(200_000, 200_000),
    )
    original = pdfplumber.page.Page.extract_text

    def guarded(self, *args, **kwargs):
        if kwargs.get("layout"):
            raise AssertionError("layout grid built for an oversized page")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(pdfplumber.page.Page, "extract_text", guarded)
    text = extract_text("poster.pdf", data)
    assert "perfectly ordinary sentence" in text


# ────────────────────────────────── Images ─────────────────────────────────


def test_image_far_above_pixel_cap_is_rejected() -> None:
    with pytest.raises(DocumentLimitError, match="pixels"):
        extract_text(
            "huge.png", _png((2_100, 2_000)), limits=ParserLimits(ocr_max_pixels=1_000_000)
        )


def test_image_above_pixel_cap_is_downscaled_before_ocr(monkeypatch) -> None:
    import pytesseract

    seen: list[tuple[int, int]] = []

    def fake_ocr(image, *args, **kwargs):
        seen.append(image.size)
        return "scanned"

    monkeypatch.setattr(pytesseract, "image_to_string", fake_ocr)
    text = extract_text(
        "photo.png", _png((1_500, 1_000)), limits=ParserLimits(ocr_max_pixels=1_000_000)
    )
    assert text == "scanned"
    assert seen and seen[0][0] * seen[0][1] <= 1_000_000


# ───────────────────────────────── Archives ────────────────────────────────


def _docx_bomb(payload_bytes: int) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<w:document/>")
        archive.writestr("word/media/bomb.bin", b"\x00" * payload_bytes)
    return buf.getvalue()


def test_docx_zip_bomb_is_rejected_with_default_limits() -> None:
    bomb = _docx_bomb(20 * 1024 * 1024)  # ~20 KiB on disk, 20 MiB expanded
    assert len(bomb) < 100 * 1024
    with pytest.raises(DocumentLimitError, match="compression ratio"):
        extract_text("bomb.docx", bomb)


def test_docx_uncompressed_size_cap_is_enforced_from_path(tmp_path: Path) -> None:
    path = tmp_path / "big.docx"
    path.write_bytes(_docx_bomb(64 * 1024))
    limits = ParserLimits(
        max_archive_uncompressed_bytes=32 * 1024, max_archive_compression_ratio=1e9
    )
    with pytest.raises(DocumentLimitError, match="uncompressed size"):
        extract_text_from_path("big.docx", str(path), limits=limits)


# ───────────────────────────── Process isolation ───────────────────────────


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


async def _wait_for_pid(pid_path: Path) -> int:
    for _ in range(100):
        if pid_path.exists() and pid_path.read_text():
            return int(pid_path.read_text())
        time.sleep(0.05)
    raise AssertionError("child never started")


async def test_isolated_parse_returns_result() -> None:
    assert await run_isolated(parse_helpers.echo, "hello", timeout=30) == "hello"


async def test_isolated_parse_timeout_kills_the_child(tmp_path: Path) -> None:
    pid_path = tmp_path / "child.pid"
    with pytest.raises(TimeoutError, match="exceeded 1 seconds"):
        await run_isolated(parse_helpers.hang, str(pid_path), timeout=1)
    pid = await _wait_for_pid(pid_path)
    assert pid != os.getpid()
    assert not _pid_alive(pid), "timed-out parser process must be killed, not leaked"


async def test_isolated_parse_crash_is_reported() -> None:
    with pytest.raises(ParserCrashedError, match="exit code -9"):
        await run_isolated(parse_helpers.die, timeout=30)


async def test_isolated_parse_preserves_parser_errors() -> None:
    with pytest.raises(DocumentLimitError, match="more than 3 pages"):
        await run_isolated(parse_helpers.over_limit, timeout=30)


async def test_isolated_parse_survives_unpicklable_errors() -> None:
    with pytest.raises(RuntimeError, match="_Unpicklable: left/right"):
        await run_isolated(parse_helpers.raise_unpicklable, timeout=30)


async def test_pipeline_timeout_kills_parser_and_indexes_nothing(
    tmp_path: Path, monkeypatch
) -> None:
    class _NoWrites:
        async def ensure_collection(self, *_a) -> None:
            raise AssertionError("must not reach indexing")

    pid_path = tmp_path / "pipeline.pid"
    monkeypatch.setattr(pipeline_module, "extract_text", parse_helpers.hang_parse)
    job = DocumentJob(
        document_id=str(uuid4()), workspace_id=str(uuid4()), filename="slow.txt", embedding_dim=8
    )
    started = time.monotonic()
    with pytest.raises(TimeoutError, match="document parsing exceeded 1 seconds"):
        await process_document(
            data=str(pid_path).encode(),
            job=job,
            embedder=DeterministicMockEmbedder(8),
            vector_store=_NoWrites(),
            parse_timeout_seconds=1,
        )
    assert time.monotonic() - started < 15
    assert not _pid_alive(await _wait_for_pid(pid_path))


def test_render_scale_math_is_bounded() -> None:
    from raggie_workers.ingestion.parsing import _ocr_render_scale

    assert _ocr_render_scale(612, 792, 25_000_000) == 2.0
    scale = _ocr_render_scale(14_400, 14_400, 25_000_000)
    assert (14_400 * scale) ** 2 <= 25_000_000
    assert math.isclose((14_400 * scale) ** 2, 25_000_000, rel_tol=1e-6)
    assert _ocr_render_scale(0, 792, 25_000_000) == 0.0
