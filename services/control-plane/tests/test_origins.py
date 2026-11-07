# SPDX-License-Identifier: Apache-2.0

"""Widget CORS origins are stored exactly as browsers serialize the Origin
header, because the edge compares that header byte-for-byte."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from raggie_control_plane.api.workspaces import _validate_origins, normalize_origin


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://Example.com:443/", "https://example.com"),
        ("HTTPS://EXAMPLE.COM", "https://example.com"),
        ("HTTP://LOCALHOST:80", "http://localhost"),
        ("http://localhost:3000/", "http://localhost:3000"),
        ("  https://acme.example  ", "https://acme.example"),
        # Ports are numbers: leading zeros go, default ports go.
        ("https://example.com:0443", "https://example.com"),
        ("http://example.com:08080", "http://example.com:8080"),
        # A default port only for its own scheme.
        ("http://example.com:443", "http://example.com:443"),
        ("https://example.com:80", "https://example.com:80"),
        # IDN -> punycode (UTS #46 non-transitional, as browsers do).
        ("https://bücher.de", "https://xn--bcher-kva.de"),
        ("https://BÜCHER.de/", "https://xn--bcher-kva.de"),
        ("https://straße.de", "https://xn--strae-oqa.de"),
        ("https://xn--bcher-kva.de", "https://xn--bcher-kva.de"),
        # IP literals.
        ("http://127.0.0.1:8080", "http://127.0.0.1:8080"),
        ("http://[::1]:8080/", "http://[::1]:8080"),
        ("http://[::ABCD]", "http://[::abcd]"),
        ("https://my_host.internal", "https://my_host.internal"),
    ],
)
def test_normalize_origin_matches_browser_serialization(raw: str, expected: str) -> None:
    assert normalize_origin(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "*",
        "https://*.acme.example",
        "https://acme.example/*",
        "https://acme.example/path",
        "https://acme.example/?",
        "https://acme.example?x=1",
        "https://acme.example#frag",
        "https://acme.example/#",
        "https://user@acme.example",
        "https://user:pw@acme.example",
        "https://acme.example\\@evil.com",
        "ftp://acme.example",
        "javascript:alert(1)",
        "acme.example",
        "//acme.example",
        "https://",
        "https://:443",
        "https://acme.example:",
        "https://acme.example:0",
        "https://acme.example:99999",
        "https://acme.example:abc",
        "https://exa mple.com",
        "https://acme.example\x00",
        "https://[::1",
        # Browsers parse a numeric last label as IPv4 and serialize it dotted-
        # decimal; a non-canonical spelling could never match.
        "https://0x7f.1",
        "http://127.1",
        "http://2130706433",
        "http://127.0.0.256",
        "http://1.2.3.04",
    ],
)
def test_normalize_origin_rejects_non_origins(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_origin(raw)


def test_validate_origins_normalizes_dedupes_and_skips_blanks() -> None:
    assert _validate_origins(
        ["https://A.com", "", "  ", "https://a.com:443/", "http://a.com", "https://b.com"]
    ) == ["https://a.com", "http://a.com", "https://b.com"]


def test_validate_origins_rejects_with_422_naming_the_entry() -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_origins(["https://ok.com", "https://bad.com/path"])
    assert exc.value.status_code == 422
    assert "https://bad.com/path" in exc.value.detail
