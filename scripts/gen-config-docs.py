#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""Generate docs/configuration.md from .env.example.

.env.example is the single source of truth for configuration. This script
turns it into a browsable reference, grouped by its section headers
(`# ───── Title ─────`), with each variable's default and the comment text that
precedes it (or follows it on the same line).

    python3 scripts/gen-config-docs.py           # (re)write docs/configuration.md
    python3 scripts/gen-config-docs.py --check   # exit 1 if the file is stale (CI)

Parsing rules:
  * `KEY=value   # note`   → a variable; text after "  #" is part of its description.
  * `# KEY=value`          → an optional variable that is commented out by default
                             (or, if KEY is also set elsewhere, an example for it).
  * consecutive `# …` lines directly above a variable describe it; a comment block
    followed by a blank line is rendered as a note paragraph.
Standard library only.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / ".env.example"
TARGET = ROOT / "docs" / "configuration.md"

SECTION_RE = re.compile(r"^#\s*─+\s*(?P<title>.+?)\s*─*\s*$")
VAR_RE = re.compile(r"^(?P<key>[A-Z][A-Z0-9_]*)=(?P<rest>.*)$")
# Exactly one space after '#': a commented-out variable. Deeper indentation is prose.
COMMENTED_VAR_RE = re.compile(r"^# (?P<key>[A-Z][A-Z0-9_]*)=(?P<rest>.*)$")
INLINE_COMMENT_RE = re.compile(r"\s+#\s?")


@dataclass
class Var:
    key: str
    default: str
    description: list[str] = field(default_factory=list)
    commented: bool = False
    examples: list[str] = field(default_factory=list)


@dataclass
class Section:
    title: str
    items: list[object] = field(default_factory=list)  # Var | str (note)


def split_value(rest: str) -> tuple[str, str]:
    """`value   # comment` → (value, comment). A '#' only starts a comment when
    preceded by whitespace, so URLs or values containing '#' survive."""
    m = INLINE_COMMENT_RE.search(rest)
    if not m:
        return rest.strip(), ""
    return rest[: m.start()].strip(), rest[m.end() :].strip()


def parse(text: str) -> list[Section]:
    sections: list[Section] = [Section("General")]
    pending: list[str] = []  # comment lines not yet attached to a variable

    def flush_note() -> None:
        if pending:
            sections[-1].items.append(" ".join(pending))
            pending.clear()

    lines = text.splitlines()
    # Skip the file banner (comment lines before the first blank line or section).
    i = 0
    while i < len(lines) and lines[i].startswith("#") and not SECTION_RE.match(lines[i]):
        i += 1

    for raw in lines[i:]:
        line = raw.rstrip()
        if not line.strip():
            flush_note()
            continue
        sm = SECTION_RE.match(line)
        if sm:
            flush_note()
            sections.append(Section(sm.group("title")))
            continue
        cm = COMMENTED_VAR_RE.match(line)
        vm = VAR_RE.match(line)
        if vm or cm:
            m = vm or cm
            value, inline = split_value(m.group("rest"))
            desc = list(pending)
            if inline:
                desc.append(inline)
            pending.clear()
            sections[-1].items.append(
                Var(key=m.group("key"), default=value, description=desc, commented=cm is not None)
            )
            continue
        if line.startswith("#"):
            pending.append(line.lstrip("#").strip())
            continue
        # Anything else is unexpected in an env file; keep it visible as a note.
        pending.append(line.strip())
    flush_note()

    # A commented-out KEY that is also defined for real is an example of it.
    real = {
        item.key: item
        for s in sections
        for item in s.items
        if isinstance(item, Var) and not item.commented
    }
    for s in sections:
        kept: list[object] = []
        for item in s.items:
            if isinstance(item, Var) and item.commented and item.key in real:
                real[item.key].examples.append(f"{item.key}={item.default}")
                continue
            kept.append(item)
        s.items = kept
    return [s for s in sections if s.items]


def md_text(text: str, keys: set[str]) -> str:
    """Escape markdown/HTML-sensitive characters and code-format env names."""
    out: list[str] = []
    # Keep existing `code` spans verbatim; escape everything else.
    for n, part in enumerate(re.split(r"(`[^`]*`)", text)):
        if n % 2 == 1:
            out.append(part)
            continue
        # Code-format env names (with an optional =value) on the raw text, so a
        # value such as <password> is not cut at the ";" of an escaped "&lt;".
        part = re.sub(
            r"\b([A-Z][A-Z0-9_]{2,})(=[^\s,;)]*)?",
            lambda m: f"`{m.group(0)}`" if m.group(1) in keys else m.group(0),
            part,
        )
        # Then escape only what stayed outside code spans.
        for m, piece in enumerate(re.split(r"(`[^`]*`)", part)):
            if m % 2 == 0:
                piece = (
                    piece.replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
                    .replace("|", "\\|")
                )
            out.append(piece)
    return "".join(out)


def md_code(value: str) -> str:
    if value == "":
        return "*(empty)*"
    tick = "``" if "`" in value else "`"
    return f"{tick}{value.replace('|', chr(92) + '|')}{tick}"


def anchor(title: str) -> str:
    """GitHub-style heading anchor: drop punctuation, one hyphen per space."""
    return re.sub(r"[^\w\s-]", "", title.lower()).strip().replace(" ", "-")


def render(sections: list[Section]) -> str:
    keys = {i.key for s in sections for i in s.items if isinstance(i, Var)}
    total = sum(1 for s in sections for i in s.items if isinstance(i, Var))
    out = [
        "<!-- Generated by scripts/gen-config-docs.py from .env.example. Do not edit by hand:",
        "     change .env.example, then run `make config-docs`. -->",
        "",
        "# Configuration reference",
        "",
        "Raggie is configured through environment variables. The canonical list, with",
        "safe defaults, is [`.env.example`](../.env.example); this page is generated",
        f"from it ({total} variables). `make env` copies it to `.env`; `install.sh`",
        "generates every secret for you.",
        "",
        "> **Production:** set `RAGGIE_ENV=production` (the installer does). Outside",
        "> development every service refuses to start with default, placeholder or",
        "> short secrets. See [production.md](production.md).",
        "",
        "Columns: **Default** is the value shipped in `.env.example` (*(empty)* means",
        "unset; most services then use a built-in default described in the notes).",
        "Variables marked *optional* are commented out in `.env.example`.",
        "",
        "## Sections",
        "",
    ]
    out += [f"- [{s.title}](#{anchor(s.title)})" for s in sections]
    for s in sections:
        out += ["", f"## {s.title}", ""]
        table_open = False
        for item in s.items:
            if isinstance(item, str):
                if table_open:
                    out.append("")
                    table_open = False
                out += [md_text(item, keys), ""]
                continue
            if not table_open:
                out += ["| Variable | Default | Description |", "|---|---|---|"]
                table_open = True
            desc = md_text(" ".join(item.description), keys)
            if item.commented:
                desc = (desc + " " if desc else "") + "*Optional — commented out by default.*"
            for ex in item.examples:
                desc += f"<br>Example: {md_code(ex)}"
            out.append(f"| `{item.key}` | {md_code(item.default)} | {desc} |")
        if table_open:
            out.append("")
    text = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", text).rstrip() + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="fail if docs/configuration.md is stale")
    args = ap.parse_args()
    rendered = render(parse(SOURCE.read_text(encoding="utf-8")))
    if args.check:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current != rendered:
            print(
                f"{TARGET.relative_to(ROOT)} is stale; run: make config-docs",
                file=sys.stderr,
            )
            return 1
        print(f"{TARGET.relative_to(ROOT)} is up to date")
        return 0
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(rendered, encoding="utf-8")
    print(f"wrote {TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
