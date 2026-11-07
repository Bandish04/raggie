# SPDX-License-Identifier: Apache-2.0

from raggie_workers.evaluation.citations import analyze_citations, extract_citations


def test_extracts_multiple_and_range_citations():
    assert extract_citations("A [1, 3]. B [4-6].") == [1, 3, 4, 5, 6]


def test_validity_and_claim_coverage_are_separate():
    metrics = analyze_citations(
        "Paris is the capital of France [1]. It has a large population.",
        source_count=2,
    )
    assert metrics.validity_score == 1.0
    assert metrics.coverage_score == 0.5
    assert metrics.claim_count == 2
    assert metrics.cited_claim_count == 1


def test_out_of_range_citation_is_reported():
    metrics = analyze_citations("The policy starts in June [3].", source_count=2)
    assert metrics.validity_score == 0.0
    assert metrics.invalid_indices == [3]
    assert metrics.coverage_score == 0.0


def test_no_sources_and_no_citation_is_not_spuriously_scored():
    metrics = analyze_citations("Merhaba.", source_count=0)
    assert metrics.validity_score is None
    assert metrics.coverage_score is None
