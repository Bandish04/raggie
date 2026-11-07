#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Keep a one-line SPDX license header on every first-party source file.

    scripts/license/spdx.py           add the header where it is missing
    scripts/license/spdx.py --check   list files without one, exit 1 (CI)

Covers Go, Python, TS/TSX/JS, shell, SQL and Dockerfiles among the files git
tracks or would track (untracked files honour .gitignore). The header goes
after anything that must stay first: a shebang, a Python encoding cookie,
Dockerfile parser directives (``# syntax=``). Generated files ("Code generated
... DO NOT EDIT", ``@generated``), vendored code, test data, examples and docs
are skipped. The copyright line lives in NOTICE, so the header is SPDX only.
Stdlib only, so CI needs nothing beyond Python.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

LICENSE = "Apache-2.0"
HEADER = f"SPDX-License-Identifier: {LICENSE}"

_SLASH = frozenset({".go", ".ts", ".tsx", ".js", ".mjs", ".cjs"})
_HASH = frozenset({".py", ".sh"})
_DASH = frozenset({".sql"})
_SKIP_DIRS = frozenset({"node_modules", ".next", "testdata", "vendor", "__pycache__"})
_SKIP_TOP = frozenset({"examples", "docs", "internal", "CC-Session-Logs", ".semgrep"})
_SKIP_FILES = frozenset({"next-env.d.ts"})
_SCAN_LINES = 10  # an existing header / generated marker must sit near the top

_GENERATED = re.compile(r"Code generated .* DO NOT EDIT|@generated")
_CODING = re.compile(r"^[ \t\f]*#.*?coding[:=]")
_DOCKER_DIRECTIVE = re.compile(r"^#\s*(syntax|escape|check)\s*=", re.IGNORECASE)


def _is_dockerfile(path: PurePosixPath | Path) -> bool:
    return path.name == "Dockerfile" or path.name.startswith("Dockerfile.")


def _comment(path: Path) -> str | None:
    if _is_dockerfile(path) or path.suffix in _HASH:
        return "#"
    if path.suffix in _SLASH:
        return "//"
    if path.suffix in _DASH:
        return "--"
    return None


def is_target(path: str) -> bool:
    """True for a first-party source file (repo-relative, POSIX separators)."""
    p = PurePosixPath(path)
    if p.parts[0] in _SKIP_TOP or _SKIP_DIRS.intersection(p.parts[:-1]):
        return False
    if p.name in _SKIP_FILES:
        return False
    return _comment(Path(path)) is not None


def with_header(path: Path, text: str) -> str | None:
    """``text`` with the SPDX header inserted, or None when it already has one
    (or must not get one: generated code)."""
    comment = _comment(path)
    if comment is None:
        return None
    head = text.splitlines()[:_SCAN_LINES]
    if any(HEADER in line or _GENERATED.search(line) for line in head):
        return None
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    at = 0
    if lines and lines[0].startswith("#!"):
        at = 1
    if path.suffix == ".py":
        while at < min(len(lines), 2) and _CODING.match(lines[at]):
            at += 1
    if _is_dockerfile(path):
        while at < len(lines) and _DOCKER_DIRECTIVE.match(lines[at]):
            at += 1
    if at and not lines[at - 1].endswith(("\n", "\r")):
        lines[at - 1] += newline
    insert = [f"{comment} {HEADER}{newline}"]
    rest = lines[at:]
    if rest and rest[0].strip():
        # Join a following comment block in '#'/'--' languages; in Go/JS a
        # blank line keeps the header out of the next doc comment.
        if comment == "//" or not rest[0].lstrip().startswith(comment):
            insert.append(newline)
    return "".join(lines[:at] + insert + rest)


def run(paths: list[Path], *, fix: bool) -> list[Path]:
    """Paths missing a header (fixed in place when ``fix``)."""
    missing: list[Path] = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        updated = with_header(path, text)
        if updated is None:
            continue
        missing.append(path)
        if fix:
            with path.open("w", encoding="utf-8", newline="") as fh:
                fh.write(updated)
    return missing


def tracked_targets(root: Path) -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout.decode()
    names = sorted({n for n in out.split("\0") if n and is_target(n)})
    return [root / n for n in names if (root / n).is_file()]  # skip worktree deletions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="report only; exit 1 if missing")
    args = parser.parse_args(argv)
    root = Path(
        subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], check=True, capture_output=True, text=True
        ).stdout.strip()
    )
    missing = run(tracked_targets(root), fix=not args.check)
    for path in missing:
        print(path.relative_to(root))
    if args.check and missing:
        print(
            f"{len(missing)} file(s) lack '{HEADER}'; run scripts/license/spdx.py",
            file=sys.stderr,
        )
        return 1
    if not args.check:
        print(f"added the header to {len(missing)} file(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
