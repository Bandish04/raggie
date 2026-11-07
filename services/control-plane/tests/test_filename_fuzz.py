# SPDX-License-Identifier: Apache-2.0

"""Property tests for the upload filename sanitizer (object-key component)."""

import re

from hypothesis import given, settings
from hypothesis import strategies as st

from raggie_control_plane.api.documents import _safe_filename

_ALLOWED = re.compile(r"^[A-Za-z0-9._()\-]+$")

# Bias toward the characters that matter: separators, dots, control chars.
_NAMES = st.text(
    alphabet=st.sampled_from(list('/\\.\x00\x1f\x7f\n\r\t :*?"<>|%~ aZ9-_()çİ😀')),
    max_size=300,
) | st.text(max_size=300)


@settings(max_examples=300, deadline=500)
@given(name=_NAMES)
def test_sanitized_name_is_a_single_safe_path_component(name) -> None:
    out = _safe_filename(name)
    assert out and len(out) <= 200
    assert _ALLOWED.match(out), out
    assert "/" not in out and "\\" not in out
    assert ".." not in out and not out.startswith(".")
    assert not any(ord(ch) < 32 or ord(ch) == 127 for ch in out)


def test_known_traversal_inputs() -> None:
    for name in ("..", "../../etc/passwd", "..\\..\\boot.ini", "....pdf", ".hidden.pdf", "./a"):
        out = _safe_filename(name)
        assert ".." not in out and not out.startswith(".") and "/" not in out, (name, out)
    assert _safe_filename("Rapor 2026 (son).pdf") == "Rapor_2026_(son).pdf"
