#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Fail a release on unapproved "Review required" entries in THIRD_PARTY_NOTICES.md.

    scripts/notices/check_review.py [--notices THIRD_PARTY_NOTICES.md]
                                    [--allowlist scripts/notices/review-allowlist.txt]

Every row of the generator's "Review required" table (copyleft, non-commercial
or unknown license) must match an allowlist line:

    <package name or glob><TAB><exact license expression><TAB><justification>

The license must match exactly, so a dependency that changes its license comes
back for review. Exit codes: 0 all approved, 1 unapproved rows, 2 the notices
file or the allowlist cannot be read or has no "Review required" section.
"""

from __future__ import annotations

import argparse
import fnmatch
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SECTION = "## Review required"
_CELL_SPLIT = re.compile(r"(?<!\\)\|")


@dataclass(frozen=True)
class Row:
    component: str
    package: str
    version: str
    license: str
    category: str


@dataclass(frozen=True)
class Approval:
    pattern: str
    license: str
    justification: str

    def covers(self, row: Row) -> bool:
        return fnmatch.fnmatchcase(row.package, self.pattern) and row.license == self.license


def _cells(line: str) -> list[str]:
    inner = line.strip().strip("|")
    return [c.strip().replace("\\|", "|") for c in _CELL_SPLIT.split(inner)]


def review_rows(markdown: str) -> list[Row]:
    lines = markdown.splitlines()
    try:
        start = lines.index(SECTION)
    except ValueError:
        raise ValueError(f"no '{SECTION}' section") from None
    rows: list[Row] = []
    for line in lines[start + 1 :]:
        if line.startswith("## "):
            break
        if not line.startswith("|") or line.startswith("|---"):
            continue
        cells = _cells(line)
        if cells[:2] == ["Component", "Package"]:
            continue
        if len(cells) != 5:
            raise ValueError(f"malformed review row: {line!r}")
        rows.append(Row(*cells))
    return rows


def load_allowlist(path: Path) -> list[Approval]:
    approvals: list[Approval] = []
    for n, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        cols = [c.strip() for c in line.split("\t")]
        if len(cols) != 3 or not all(cols):
            raise ValueError(f"{path}:{n}: expected <package>\\t<license>\\t<justification>")
        approvals.append(Approval(*cols))
    return approvals


def unapproved(rows: list[Row], approvals: list[Approval]) -> list[Row]:
    return [r for r in rows if not any(a.covers(r) for a in approvals)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--notices", type=Path, default=ROOT / "THIRD_PARTY_NOTICES.md")
    parser.add_argument(
        "--allowlist", type=Path, default=ROOT / "scripts" / "notices" / "review-allowlist.txt"
    )
    args = parser.parse_args(argv)
    try:
        rows = review_rows(args.notices.read_text())
        approvals = load_allowlist(args.allowlist)
    except (OSError, ValueError) as exc:
        print(f"check_review: {exc}", file=sys.stderr)
        return 2

    left = unapproved(rows, approvals)
    for r in left:
        print(
            f"::error::license review required: {r.package} {r.version} ({r.license}, "
            f"{r.category}) in {r.component} is not in {args.allowlist.name}"
        )
    used = {a for a in approvals for r in rows if a.covers(r)}
    for a in approvals:
        if a not in used:
            print(f"::notice::allowlist entry no longer needed: {a.pattern} ({a.license})")
    print(f"check_review: {len(rows)} review row(s), {len(left)} unapproved")
    return 1 if left else 0


if __name__ == "__main__":
    sys.exit(main())
