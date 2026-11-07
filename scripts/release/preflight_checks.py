#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Helpers for scripts/release-preflight.sh (stdlib only; run from the repo root).

    preflight_checks.py release-awk      print the release-notes awk program of release.yml
    preflight_checks.py i18n DIR         compare every DIR/*.json with DIR/en.json
    preflight_checks.py images           list unpinned and digest-less images
    preflight_checks.py forbidden RULES  scan the NUL-separated paths on stdin

i18n and images print one result line and exit 1 on a problem. forbidden prints
"STATUS<TAB>CHECK<TAB>DETAIL" rows (FAIL per matching rule and for unreadable
files, WARN for documents whose text cannot be extracted) and exits 0; 2 on a
usage error. Text files are scanned as they are; PDFs through pdftotext when it
is installed (RELEASE_PREFLIGHT_PDFTOTEXT=PATH|none) plus their Flate streams,
OOXML documents (docx/xlsx/pptx) through their XML parts; other binary files
are skipped, like grep -I.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
import zipfile
import zlib
from pathlib import Path

RELEASE_YML = Path(".github/workflows/release.yml")
_AWK = re.compile(r"awk -v v=\"\$version\" '\n(.*?)\n\s*' CHANGELOG\.md", re.S)
_IMAGE = re.compile(r"""^\s*-?\s*(?:image|imageName):\s*["']?([^"'\s{#]+)""")


def release_awk() -> int:
    if not RELEASE_YML.is_file():
        return 1
    m = _AWK.search(RELEASE_YML.read_text(encoding="utf-8"))
    if not m:
        return 1
    print(textwrap.dedent(m.group(1)))
    return 0


def _no_duplicates(pairs: list[tuple[str, object]]) -> dict:
    out: dict = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate key {key!r}")
        out[key] = value
    return out


def _paths(node: object, prefix: str = "") -> set[str]:
    if not isinstance(node, dict):
        return {prefix[:-1]}
    found: set[str] = set()
    for key, value in node.items():
        found |= _paths(value, f"{prefix}{key}.")
    return found


def i18n(directory: str) -> int:
    root = Path(directory)
    if not (root / "en.json").is_file():
        print(f"{root}/en.json not found")
        return 1
    problems: list[str] = []
    keys: dict[str, set[str]] = {}
    for f in sorted(root.glob("*.json")):
        try:
            doc = json.loads(f.read_text("utf-8"), object_pairs_hook=_no_duplicates)
            keys[f.name] = _paths(doc)
        except ValueError as exc:
            problems.append(f"{f.name}: {exc}")
    ref = keys.get("en.json", set())
    for name, found in keys.items():
        if missing := sorted(ref - found)[:5]:
            problems.append(f"{name} lacks {', '.join(missing)}")
        if extra := sorted(found - ref)[:5]:
            problems.append(f"{name} has extra {', '.join(extra)}")
    if problems:
        print("; ".join(problems))
        return 1
    print(f"{len(keys)} catalog(s) x {len(ref)} keys")
    return 0


def images() -> int:
    files = sorted(
        {
            *Path("deploy/compose").glob("*.y*ml"),
            *Path("deploy/helm").rglob("values*.yaml"),
            *Path("deploy/k8s").rglob("*.yaml"),
        }
    )
    bad: list[str] = []
    floating: list[str] = []
    for f in files:
        for n, line in enumerate(f.read_text("utf-8").splitlines(), 1):
            m = _IMAGE.match(line)
            if not m or "{{" in line:
                continue
            name, _, digest = m.group(1).partition("@")
            if name.startswith("raggie/"):
                continue  # built from this repo; a release swaps in the published images
            last = name.rsplit("/", 1)[-1]
            tag = last.split(":", 1)[1] if ":" in last else ""
            where = f"{f}:{n} {name}"
            if tag == "latest" or (not tag and not digest):
                bad.append(where)
            elif not digest.startswith("sha256:"):
                floating.append(where)
    for item in bad:
        print(f"BAD\t{item}")
    for item in floating:
        print(f"FLOAT\t{item}")
    return 1 if bad else 0


_POSIX_CLASSES = {
    "[:space:]": r"\s",
    "[:digit:]": "0-9",
    "[:alpha:]": "A-Za-z",
    "[:alnum:]": "A-Za-z0-9",
    "[:upper:]": "A-Z",
    "[:lower:]": "a-z",
}
_STREAM = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.S)
_TAG = re.compile(rb"<[^>]+>")


def _ere(pattern: str) -> re.Pattern[bytes]:
    """A forbidden.txt extended regex (grep -E) as a bytes regex."""
    for cls, repl in _POSIX_CLASSES.items():
        pattern = pattern.replace(cls, repl)
    return re.compile(pattern.encode("utf-8"))


def _pdftotext() -> str | None:
    choice = os.environ.get("RELEASE_PREFLIGHT_PDFTOTEXT", "")
    if choice == "none":
        return None
    return choice or shutil.which("pdftotext")


def _pdf_texts(path: str, data: bytes) -> tuple[list[bytes], bool]:
    """Searchable blobs of a PDF, and whether any text could be extracted."""
    blobs = [data]
    decoded = 0
    for m in _STREAM.finditer(data):
        try:
            blobs.append(zlib.decompress(m.group(1)))
            decoded += 1
        except zlib.error:
            continue
    tool = _pdftotext()
    if tool:
        try:
            proc = subprocess.run(
                [tool, "-q", "-enc", "UTF-8", path, "-"],
                capture_output=True,
                timeout=120,
                check=False,
            )
            if proc.returncode == 0:
                return blobs + [proc.stdout], True
        except (OSError, subprocess.SubprocessError):
            pass
    return blobs, decoded > 0 and b"/Encrypt" not in data


def _ooxml_texts(data: bytes, path: str) -> tuple[list[bytes], bool]:
    try:
        with zipfile.ZipFile(path) as z:
            blobs = []
            for name in z.namelist():
                if name.endswith((".xml", ".rels")):
                    xml = z.read(name)
                    blobs += [xml, _TAG.sub(b"", xml)]
            return blobs, True
    except (zipfile.BadZipFile, OSError, RuntimeError, ValueError):
        return [], False


def _is_ooxml(data: bytes, path: str) -> bool:
    if not data.startswith(b"PK\x03\x04"):
        return False
    try:
        with zipfile.ZipFile(path) as z:
            return "[Content_Types].xml" in z.namelist()
    except (zipfile.BadZipFile, OSError):
        return True  # looks like one; reported as unextractable


def _show(name: str) -> str:
    """The name with control characters escaped (a newline becomes \\n)."""
    return "".join(c if c.isprintable() else repr(c)[1:-1] for c in name)


def _listing(names: list[str]) -> str:
    shown = ", ".join(_show(n) for n in names[:3])
    return shown + (f" (+{len(names) - 3} more)" if len(names) > 3 else "")


def forbidden(rules_file: str) -> int:
    content: list[tuple[re.Pattern[bytes], str]] = []
    paths: list[tuple[str, str]] = []
    rows: list[str] = []
    for line in Path(rules_file).read_text("utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        kind, pattern, reason = (line.split("\t") + ["", ""])[:3]
        if kind == "content":
            try:
                content.append((_ere(pattern), reason))
            except re.error as exc:
                rows.append(f"FAIL\tforbidden\tbad pattern {pattern!r} in {rules_file}: {exc}")
        elif kind == "path":
            paths.append((pattern, reason))
        else:
            rows.append(f"FAIL\tforbidden\tunknown rule kind {kind!r} in {rules_file}")
    names = [
        raw.decode("utf-8", "surrogateescape")
        for raw in sys.stdin.buffer.read().split(b"\0")
        if raw
    ]
    hits: dict[str, list[str]] = {}
    unreadable: list[str] = []
    unextractable: list[str] = []
    for name in names:
        if name == rules_file or not os.path.isfile(name):
            continue
        for pattern, reason in paths:
            if fnmatch.fnmatchcase(name, pattern):
                hits.setdefault(reason, []).append(name)
        if not content:
            continue
        try:
            data = Path(name).read_bytes()
        except OSError:
            unreadable.append(name)
            continue
        if data.startswith(b"%PDF-"):
            blobs, ok = _pdf_texts(name, data)
        elif _is_ooxml(data, name):
            blobs, ok = _ooxml_texts(data, name)
        elif b"\0" in data:
            continue  # other binary files are skipped (grep -I)
        else:
            blobs, ok = [data], True
        if not ok:
            unextractable.append(name)
        for pattern, reason in content:
            if any(pattern.search(blob) for blob in blobs):
                found = hits.setdefault(reason, [])
                if name not in found:
                    found.append(name)
    for reason, found in hits.items():
        rows.append(f"FAIL\tforbidden\t{reason}: {_listing(found)}")
    if unreadable:
        n = len(unreadable)
        rows.append(f"FAIL\tforbidden\tcannot read {n} file(s): {_listing(unreadable)}")
    if unextractable:
        rows.append(
            f"WARN\tforbidden-extract\tcannot extract text from {len(unextractable)} document(s), "
            f"check them by hand: {_listing(unextractable)}"
        )
    if not any(r.startswith("FAIL") for r in rows):
        rows.append(f"PASS\tforbidden\t{len(content) + len(paths)} rule(s), no match")
    print("\n".join(rows))
    return 0


def main(argv: list[str]) -> int:
    if argv[:1] == ["release-awk"]:
        return release_awk()
    if argv[:1] == ["i18n"] and len(argv) == 2:
        return i18n(argv[1])
    if argv[:1] == ["images"]:
        return images()
    if argv[:1] == ["forbidden"] and len(argv) == 2:
        return forbidden(argv[1])
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
