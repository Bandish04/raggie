# SPDX-License-Identifier: Apache-2.0

"""Deterministic validation for numbered RAG citations such as ``[1]``."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

_CITATION_GROUP = re.compile(r"\[((?:\d+\s*(?:[,;-]\s*\d+\s*)*))\]")
_SEGMENT_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
_WORD = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True)
class CitationMetrics:
    source_count: int
    cited_indices: list[int]
    invalid_indices: list[int]
    claim_count: int
    cited_claim_count: int
    validity_score: float | None
    coverage_score: float | None

    def as_dict(self) -> dict:
        return asdict(self)


def analyze_citations(answer: str, source_count: int) -> CitationMetrics:
    references = extract_citations(answer)
    unique = sorted(set(references))
    invalid = sorted(index for index in unique if index < 1 or index > source_count)
    valid = {index for index in unique if 1 <= index <= source_count}

    claims = [segment for segment in _segments(answer) if _is_substantive_claim(segment)]
    cited_claims = sum(
        1
        for segment in claims
        if any(1 <= index <= source_count for index in extract_citations(segment))
    )

    validity: float | None
    if references:
        validity = sum(1 for index in references if 1 <= index <= source_count) / len(references)
    elif source_count > 0 and claims:
        validity = 0.0
    else:
        validity = None

    coverage = cited_claims / len(claims) if source_count > 0 and claims else None
    return CitationMetrics(
        source_count=source_count,
        cited_indices=sorted(valid),
        invalid_indices=invalid,
        claim_count=len(claims),
        cited_claim_count=cited_claims,
        validity_score=validity,
        coverage_score=coverage,
    )


def extract_citations(text: str) -> list[int]:
    """Return citation indices in occurrence order, expanding simple ranges."""
    out: list[int] = []
    for match in _CITATION_GROUP.finditer(text or ""):
        for part in re.split(r"\s*[,;]\s*", match.group(1)):
            if "-" in part:
                bounds = [piece.strip() for piece in part.split("-", 1)]
                if len(bounds) == 2 and all(piece.isdigit() for piece in bounds):
                    start, end = (int(piece) for piece in bounds)
                    if 0 < start <= end and end - start <= 20:
                        out.extend(range(start, end + 1))
                continue
            if part.strip().isdigit():
                out.append(int(part.strip()))
    return out


def _segments(answer: str) -> list[str]:
    return [
        re.sub(r"^[\s#>*+\-\d.)]+", "", segment).strip()
        for segment in _SEGMENT_SPLIT.split(answer or "")
        if segment.strip()
    ]


def _is_substantive_claim(segment: str) -> bool:
    without_citations = _CITATION_GROUP.sub("", segment)
    words = _WORD.findall(without_citations)
    return len(words) >= 4 or any(char.isdigit() for char in without_citations)
