# SPDX-License-Identifier: Apache-2.0

import pytest

from raggie_workers.ingestion.chunking import chunk_document, chunk_text


def test_sizes_and_overlap_are_deterministic() -> None:
    chunks = chunk_text("x" * 1200, size=500, overlap=50)
    assert len(chunks) == 3
    assert [len(c) for c in chunks] == [500, 500, 300]


def test_short_text_is_a_single_chunk() -> None:
    assert chunk_text("hello", size=500, overlap=50) == ["hello"]


def test_blank_text_yields_no_chunks() -> None:
    assert chunk_text("   \n\t ", size=500) == []


def test_consecutive_chunks_share_overlap() -> None:
    text = "".join(chr(65 + (i % 26)) for i in range(1000))
    chunks = chunk_text(text, size=400, overlap=40)
    # The tail of each chunk is the head of the next.
    assert chunks[0][-40:] == chunks[1][:40]


def test_invalid_overlap_rejected() -> None:
    with pytest.raises(ValueError):
        chunk_text("abc", size=100, overlap=100)


def test_packs_on_boundaries_without_splitting_words() -> None:
    text = "Alpha company is great. Beta role is cloud. Gamma city is Istanbul."
    chunks = chunk_text(text, size=30, overlap=8)
    assert len(chunks) >= 2
    vocab = set(text.replace(".", "").split())
    for c in chunks:  # every token is a whole word from the source — no mid-word cuts
        for word in c.replace(".", "").split():
            assert word in vocab


def test_repeats_heading_context_across_section_chunks() -> None:
    text = "## Sheet: Revenue\n" + "\n".join(
        f"Region {index} has revenue {index * 1000}." for index in range(20)
    )
    chunks = chunk_text(text, size=120, overlap=20)
    assert len(chunks) > 2
    assert all(chunk.startswith("## Sheet: Revenue\n") for chunk in chunks)
    assert all(len(chunk) <= 120 for chunk in chunks)


def test_nested_heading_ancestry_is_preserved() -> None:
    text = "## Slide 4: Roadmap\nLaunch target is Q4 2026.\n### Speaker notes\n" + (
        "Customer pilot begins in September. " * 12
    )
    chunks = chunk_text(text, size=140, overlap=20)
    notes = [chunk for chunk in chunks if "Customer pilot" in chunk]
    assert len(notes) > 1
    assert all(chunk.startswith("## Slide 4: Roadmap\n### Speaker notes\n") for chunk in notes)
    assert all(len(chunk) <= 140 for chunk in chunks)


def test_headingless_output_remains_backward_compatible() -> None:
    text = "Alpha company is great. Beta role is cloud. Gamma city is Istanbul."
    assert chunk_text(text, size=30, overlap=8) == [
        "Alpha company is great.",
        "great. Beta role is cloud.",
        "cloud. Gamma city is Istanbul.",
    ]


def test_overlap_never_pushes_chunk_over_size() -> None:
    text = "First sentence is compact. " + ("z" * 29)
    chunks = chunk_text(text, size=30, overlap=20)
    assert all(len(chunk) <= 30 for chunk in chunks)


def test_document_outline_captures_main_sections_and_skips_numbered_details() -> None:
    text = """\ufeff# API Gateway Yapılandırması
## Route Tanımları
## Bölüm 1: Route Tanımları - Detaylı İnceleme
Route body.
## Kimlik Doğrulama ve Yetkilendirme
## Bölüm 1: Kimlik Doğrulama - Detaylı İnceleme
Auth body.
## Rate Limiting ve Throttling
Rate body.
## SSL/TLS Yapılandırması
TLS body.
## Logging ve İzleme
Logging body.
"""
    chunks = chunk_document(text, size=500, overlap=50)

    assert chunks[0].kind == "outline"
    assert chunks[0].section_path == "# API Gateway Yapılandırması"
    assert "Route Tanımları" in chunks[0].text
    assert "Kimlik Doğrulama ve Yetkilendirme" in chunks[0].text
    assert "Rate Limiting ve Throttling" in chunks[0].text
    assert "SSL/TLS Yapılandırması" in chunks[0].text
    assert "Logging ve İzleme" in chunks[0].text
    assert "Bölüm 1:" not in chunks[0].text
    assert all(chunk.kind == "content" for chunk in chunks[1:])


def test_bom_prefixed_title_is_preserved_as_heading_ancestry() -> None:
    chunks = chunk_text(
        "\ufeff# Handbook\n## Security\nMFA is required.",
        size=100,
        overlap=10,
    )
    assert chunks == ["# Handbook\n## Security\nMFA is required."]


def test_headingless_document_has_no_synthetic_outline() -> None:
    chunks = chunk_document("A plain document with no headings.", size=100, overlap=10)
    assert len(chunks) == 1
    assert chunks[0].kind == "content"
    assert chunks[0].section_path == ""
