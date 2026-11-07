# SPDX-License-Identifier: Apache-2.0

import pytest

from raggie_workers.config import Settings


def test_faithfulness_threshold_uses_documented_env(monkeypatch) -> None:
    monkeypatch.setenv("EVAL_FAITHFULNESS_THRESHOLD", "0.82")
    settings = Settings(_env_file=None)
    assert settings.eval_faithfulness_threshold == pytest.approx(0.82)


def test_legacy_eval_score_threshold_alias_still_works(monkeypatch) -> None:
    monkeypatch.delenv("EVAL_FAITHFULNESS_THRESHOLD", raising=False)
    monkeypatch.setenv("EVAL_SCORE_THRESHOLD", "0.73")
    settings = Settings(_env_file=None)
    assert settings.eval_faithfulness_threshold == pytest.approx(0.73)


def test_parser_limits_use_documented_env(monkeypatch) -> None:
    monkeypatch.setenv("PARSER_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("PARSER_MAX_ARCHIVE_UNCOMPRESSED_BYTES", "123456")
    monkeypatch.setenv("PARSER_MAX_EXTRACTED_CHARS", "654321")
    monkeypatch.setenv("PARSER_MAX_XLSX_CELLS", "777")
    monkeypatch.setenv("PARSER_MAX_PPTX_SHAPES", "888")
    settings = Settings(_env_file=None)
    limits = settings.parser_limits()
    assert settings.parser_timeout_seconds == pytest.approx(45)
    assert limits.max_archive_uncompressed_bytes == 123456
    assert limits.max_extracted_chars == 654321
    assert limits.max_xlsx_cells == 777
    assert limits.max_pptx_shapes == 888


def test_pdf_and_ocr_limits_use_documented_env(monkeypatch) -> None:
    monkeypatch.setenv("PARSER_MAX_PDF_PAGES", "42")
    monkeypatch.setenv("PARSER_OCR_MAX_PIXELS", "1000000")
    limits = Settings(_env_file=None).parser_limits()
    assert limits.max_pdf_pages == 42
    assert limits.ocr_max_pixels == 1_000_000


def test_parser_limit_defaults() -> None:
    settings = Settings(_env_file=None)
    limits = settings.parser_limits()
    assert limits.max_pdf_pages == 1000
    assert limits.ocr_max_pixels == 25_000_000
    assert settings.parser_timeout_seconds == pytest.approx(120)


def test_short_parser_env_aliases(monkeypatch) -> None:
    monkeypatch.setenv("PARSE_MAX_PAGES", "7")
    monkeypatch.setenv("OCR_MAX_PIXELS", "2000000")
    monkeypatch.setenv("PARSE_MAX_UNCOMPRESSED_BYTES", "4096")
    monkeypatch.setenv("PARSE_TIMEOUT_SECONDS", "30")
    settings = Settings(_env_file=None)
    limits = settings.parser_limits()
    assert limits.max_pdf_pages == 7
    assert limits.ocr_max_pixels == 2_000_000
    assert limits.max_archive_uncompressed_bytes == 4096
    assert settings.parser_timeout_seconds == pytest.approx(30)


@pytest.mark.parametrize(
    ("raw", "want"), [(None, 150.0), ("420", 420.0), ("1", 10.0), ("99999", 1800.0)]
)
def test_scheduler_task_timeout_is_bounded(monkeypatch, raw, want) -> None:
    if raw is None:
        monkeypatch.delenv("SCHEDULER_TASK_TIMEOUT_SECONDS", raising=False)
    else:
        monkeypatch.setenv("SCHEDULER_TASK_TIMEOUT_SECONDS", raw)
    assert Settings(_env_file=None).scheduler_task_timeout_seconds == want


def test_eval_max_deliveries(monkeypatch) -> None:
    monkeypatch.delenv("EVAL_MAX_DELIVERIES", raising=False)
    assert Settings(_env_file=None).eval_max_deliveries == 5
    monkeypatch.setenv("EVAL_MAX_DELIVERIES", "2")
    assert Settings(_env_file=None).eval_max_deliveries == 2
