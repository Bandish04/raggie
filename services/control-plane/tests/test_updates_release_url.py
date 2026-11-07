# SPDX-License-Identifier: Apache-2.0

"""The release manifest is remote data: its `url` becomes a link in the admin
UI, so only absolute https URLs are passed through."""

import pytest

from raggie_control_plane.api.updates import _https_url


def test_https_release_url_is_kept() -> None:
    assert (
        _https_url("https://github.com/raggie/releases/v0.2.0")
        == "https://github.com/raggie/releases/v0.2.0"
    )
    assert (
        _https_url("  https://releases.example.com/v0.2.0  ")
        == "https://releases.example.com/v0.2.0"
    )


@pytest.mark.parametrize(
    "value",
    [
        "javascript:alert(1)",
        "JAVASCRIPT:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "http://releases.example.com/v0.2.0",
        "//evil.example/x",
        "/admin/updates",
        "https://",
        "",
        None,
        42,
        ["https://example.com"],
    ],
)
def test_other_release_urls_are_dropped(value: object) -> None:
    assert _https_url(value) is None
