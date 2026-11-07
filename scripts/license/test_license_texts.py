# SPDX-License-Identifier: Apache-2.0
"""The release ships the full GPL-3.0 / LGPL-3.0 texts (libvips in the web image,
LGPL-3.0 §4(b)):  uv run --with pytest pytest -q scripts/license"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from spdx import is_target

ROOT = Path(__file__).resolve().parents[2]
# Verbatim from https://www.gnu.org/licenses/ (fetched 2026-11-05).
TEXTS = {
    "licenses/GPL-3.0.txt": "3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986",
    "licenses/LGPL-3.0.txt": "e3a994d82e644b03a792a930f574002658412f62407f5fee083f2555c5f23118",
}


@pytest.mark.parametrize(("path", "sha256"), sorted(TEXTS.items()))
def test_license_text_is_the_canonical_one(path: str, sha256: str) -> None:
    assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == sha256
    assert not is_target(path)  # a verbatim text never gets an SPDX header


@pytest.mark.parametrize("path", sorted(TEXTS))
def test_notice_and_release_bundle_carry_the_text(path: str) -> None:
    assert path in (ROOT / "NOTICE").read_text(encoding="utf-8")
    assert path in (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
