# SPDX-License-Identifier: Apache-2.0

"""Memory import parser: provenance/evidence lines never become facts."""

import pytest

from raggie_control_plane.api.auth import _parse_memory_import


@pytest.mark.parametrize(
    "footer",
    [
        "Şuradan içe aktarıldı: ChatGPT",
        "Suradan ice aktarildi: ChatGPT",
        "Imported from: ChatGPT",
        "imported from: Claude",
        "- Imported from: Gemini",
    ],
)
def test_provenance_footer_is_dropped(footer) -> None:
    text = f"Preferences:\n- Prefers concise answers\n- Works in Istanbul\n{footer}"
    assert _parse_memory_import(text) == ["Prefers concise answers", "Works in Istanbul"]


def test_evidence_lines_are_dropped() -> None:
    text = "- Likes tea\nEvidence: said so in March\nKanıt: mart ayında söyledi"
    assert _parse_memory_import(text) == ["Likes tea"]
