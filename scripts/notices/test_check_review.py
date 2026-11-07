# SPDX-License-Identifier: Apache-2.0
"""Tests for check_review.py:  uv run --with pytest pytest -q scripts/notices"""

from __future__ import annotations

from pathlib import Path

import pytest
from check_review import load_allowlist, main, review_rows, unapproved

NOTICES = """# Third-party notices

Intro.

## Review required

Copyleft, non-commercial or unidentified licenses — check before a release.

| Component | Package | Version | License | Category |
|---|---|---|---|---|
| Python — services/workers | certifi | 2026.10.23 | MPL-2.0 | weak copyleft |
| npm — web (production dependencies) | @img/sharp-libvips-linuxmusl-x64 | 1.3.4 | LGPL-3.0-or-later | weak copyleft |
| Models (MODELS.md) | jinaai/jina-reranker-v2-base-multilingual | 9cfeff2d | CC-BY-NC-4.0 | non-commercial / source-available |
| npm — web (production dependencies) | left-pad\\|fork | 1.0.0 | UNKNOWN | unknown |

## Go — services/edge

| Package | Version | License | URL |
|---|---|---|---|
| golang.org/x/net | v0.30.0 | BSD-3-Clause | https://pkg.go.dev |
"""

ALLOWLIST = (
    "# package-glob\tlicense\tjustification\n"
    "certifi\tMPL-2.0\tunmodified CA bundle, MPL is file-level\n"
    "@img/sharp-libvips-*\tLGPL-3.0-or-later\tlibvips is dynamically linked, unmodified\n"
)


@pytest.fixture
def allowlist(tmp_path: Path) -> list:
    path = tmp_path / "review-allowlist.txt"
    path.write_text(ALLOWLIST)
    return load_allowlist(path)


def test_review_rows_reads_only_the_review_table() -> None:
    rows = review_rows(NOTICES)
    assert [(r.package, r.license) for r in rows] == [
        ("certifi", "MPL-2.0"),
        ("@img/sharp-libvips-linuxmusl-x64", "LGPL-3.0-or-later"),
        ("jinaai/jina-reranker-v2-base-multilingual", "CC-BY-NC-4.0"),
        ("left-pad|fork", "UNKNOWN"),
    ]


def test_review_rows_none_section() -> None:
    assert review_rows("# T\n\n## Review required\n\nNone.\n\n## Go\n") == []


def test_review_rows_fails_closed_without_the_section() -> None:
    with pytest.raises(ValueError, match="Review required"):
        review_rows("# T\n\n## Go\n")


def test_allowlist_matches_package_glob_and_exact_license(allowlist) -> None:
    left = unapproved(review_rows(NOTICES), allowlist)
    assert [r.package for r in left] == [
        "jinaai/jina-reranker-v2-base-multilingual",
        "left-pad|fork",
    ]


def test_license_change_needs_a_new_review(allowlist) -> None:
    changed = NOTICES.replace(
        "| certifi | 2026.10.23 | MPL-2.0 |", "| certifi | 2027.1.1 | GPL-3.0 |"
    )
    assert "certifi" in [r.package for r in unapproved(review_rows(changed), allowlist)]


def test_allowlist_requires_a_justification(tmp_path: Path) -> None:
    path = tmp_path / "a.txt"
    path.write_text("certifi\tMPL-2.0\n")
    with pytest.raises(ValueError, match="justification"):
        load_allowlist(path)


def test_main_exit_codes(tmp_path: Path) -> None:
    notices = tmp_path / "THIRD_PARTY_NOTICES.md"
    allow = tmp_path / "review-allowlist.txt"
    allow.write_text(ALLOWLIST)

    notices.write_text(NOTICES)
    assert main(["--notices", str(notices), "--allowlist", str(allow)]) == 1

    approved = "\n".join(
        line for line in NOTICES.splitlines() if "jina" not in line and "left-pad" not in line
    )
    notices.write_text(approved)
    assert main(["--notices", str(notices), "--allowlist", str(allow)]) == 0

    notices.write_text("# T\n")
    assert main(["--notices", str(notices), "--allowlist", str(allow)]) == 2
