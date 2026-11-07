# SPDX-License-Identifier: Apache-2.0

"""The parser child runs in its own process group, so a timeout or crash also
takes down what it started (pytesseract's `tesseract`), and OCR calls get the
remaining parse budget as their own timeout."""

from __future__ import annotations

import io
import os
import shutil
import time
from pathlib import Path

import parse_helpers  # tests/ is on sys.path; the child re-imports it
import pytest

from raggie_workers.ingestion import isolation
from raggie_workers.ingestion.isolation import ParserCrashedError, run_isolated
from raggie_workers.ingestion.parsing import extract_text

posix_only = pytest.mark.skipif(
    os.name != "posix" or shutil.which("sleep") is None, reason="POSIX process groups"
)


def _gone(pid: int, within: float = 5.0) -> bool:
    deadline = time.monotonic() + within
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.05)
    return False


def _read_pid(path: Path) -> int:
    for _ in range(100):
        if path.exists() and path.read_text():
            return int(path.read_text())
        time.sleep(0.05)
    raise AssertionError("grandchild never started")


@posix_only
async def test_timeout_kills_the_parsers_grandchildren(tmp_path: Path) -> None:
    pid_path = tmp_path / "grandchild.pid"
    with pytest.raises(TimeoutError):
        await run_isolated(parse_helpers.spawn_and_hang, str(pid_path), timeout=1)
    assert _gone(_read_pid(pid_path)), "tesseract-like grandchild survived the timeout"


@posix_only
async def test_crashed_parser_does_not_leave_grandchildren(tmp_path: Path) -> None:
    pid_path = tmp_path / "grandchild.pid"
    with pytest.raises(ParserCrashedError):
        await run_isolated(parse_helpers.spawn_and_die, str(pid_path), timeout=30)
    assert _gone(_read_pid(pid_path)), "grandchild survived its parser's crash"


async def test_child_knows_its_remaining_budget() -> None:
    budget = await run_isolated(parse_helpers.remaining_budget, timeout=10)
    assert budget is not None and 0 < budget <= 10
    assert isolation.remaining_budget() is None  # no deadline outside a parser child


def _png() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("L", (64, 64), color=255).save(buf, format="PNG")
    return buf.getvalue()


def _blank_pdf() -> bytes:
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.showPage()
    c.save()
    return buf.getvalue()


@pytest.mark.parametrize(("name", "data"), [("scan.png", _png), ("scan.pdf", _blank_pdf)])
def test_ocr_gets_the_remaining_budget_as_its_timeout(monkeypatch, name, data) -> None:
    import pytesseract

    timeouts: list[float] = []

    def fake_ocr(_image, *args, **kwargs):
        timeouts.append(kwargs.get("timeout"))
        return "text"

    monkeypatch.setattr(pytesseract, "image_to_string", fake_ocr)
    monkeypatch.setattr(isolation, "_deadline", time.monotonic() + 20)
    extract_text(name, data())
    assert timeouts and 17 <= timeouts[0] <= 19  # remaining budget minus a margin

    monkeypatch.setattr(isolation, "_deadline", None)
    timeouts.clear()
    extract_text(name, data())
    assert timeouts == [0]  # in-process call: pytesseract's "no limit"


@posix_only
async def test_grandchildren_get_sigterm_before_sigkill(tmp_path: Path) -> None:
    marker = tmp_path / "term.txt"
    with pytest.raises(TimeoutError):
        await run_isolated(parse_helpers.spawn_graceful_and_hang, str(marker), timeout=1)
    for _ in range(100):
        if marker.exists():
            break
        time.sleep(0.05)
    assert marker.read_text().strip() == "term"
