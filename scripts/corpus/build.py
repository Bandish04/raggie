# SPDX-License-Identifier: Apache-2.0
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "reportlab==5.1.0",
#     "python-docx==1.2.0",
#     "openpyxl==3.1.5",
#     "python-pptx==1.0.2",
#     "pillow==12.3.0",
#     "matplotlib==3.11.2",
# ]
# ///
"""Regenerate the synthetic sample corpus (examples/sample-corpus).

    uv run scripts/corpus/build.py                 # every department
    uv run scripts/corpus/build.py --only finans   # one or more folders
    uv run scripts/corpus/build.py --clean         # also drop stale files

Documents are defined in scripts/corpus/content/<department>.py (one module per
corpus folder, each exporting DOCS). Output is deterministic: fixed creation
dates, no author metadata, fixed ZIP timestamps, seeded image noise.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from content import load_docs  # noqa: E402 (needs the sys.path entry above)
from renderers import RENDERERS  # noqa: E402

REPO = HERE.parent.parent
DEFAULT_OUT = REPO / "examples" / "sample-corpus"
KEEP = {"README.md"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--only", default="", help="comma-separated department folders")
    parser.add_argument(
        "--clean",
        action="store_true",
        help="delete files in the built folders that no content module defines",
    )
    args = parser.parse_args(argv)

    only = {f.strip() for f in args.only.split(",") if f.strip()}
    docs = [d for d in load_docs() if not only or d.folder in only]
    names = [d.name for d in load_docs()]
    dupes = {n for n in names if names.count(n) > 1}
    if dupes:
        print(f"duplicate file names across the corpus: {sorted(dupes)}", file=sys.stderr)
        return 1

    built: dict[str, set[str]] = {}
    for doc in docs:
        renderer = RENDERERS.get(doc.ext)
        if renderer is None:
            print(f"{doc.path}: no renderer for {doc.ext}", file=sys.stderr)
            return 1
        out = args.out / doc.path
        renderer(doc, out)
        built.setdefault(doc.folder, set()).add(doc.name)
        print(f"  {doc.path}  ({out.stat().st_size:,} B)")

    if args.clean:
        for folder, keep in built.items():
            for path in sorted((args.out / folder).iterdir()):
                if path.is_file() and path.name not in keep and path.name not in KEEP:
                    path.unlink()
                    print(f"  removed stale {folder}/{path.name}")
    print(f"built {len(docs)} document(s) into {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
