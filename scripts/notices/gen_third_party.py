#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Generate THIRD_PARTY_NOTICES.md from the lockfiles.

    scripts/notices/gen_third_party.py [--output THIRD_PARTY_NOTICES.md]

Per component it lists every shipped (non-dev) dependency with its version,
license and URL, and puts anything copyleft, non-commercial or of unknown
license in a "Review required" section at the top:

* Go (services/edge, bench): ``go-licenses report`` (pinned), versions from
  ``go list -m``; built with the module's own toolchain.
* Python (services/control-plane, workers, embeddings): ``uv export --frozen
  --no-dev`` resolved against PyPI's JSON API (license expression, then trove
  classifiers) — nothing is installed.
* npm (web): ``pnpm licenses list --prod --json``; needs ``pnpm install`` in
  web/. Optional platform packages (e.g. sharp's libvips) are the ones installed
  on the machine that runs this; generate on Linux for the shipped image.
* Fonts and icons (web/app/fonts, web/public/fonts) and models (MODELS.md).

Needs go, uv, pnpm and network access (Go module proxy, PyPI). No Docker.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

GO_LICENSES = "github.com/google/go-licenses/v2@v2.0.1"
FIRST_PARTY_GO = "github.com/alicangunduz/raggie"
GO_MODULES = ("services/edge", "bench")
PY_PROJECTS = ("services/control-plane", "services/workers", "services/embeddings")
WEB = "web"
PYPI = "https://pypi.org/pypi/{name}/{version}/json"

PERMISSIVE = "permissive"
WEAK_COPYLEFT = "weak copyleft"
COPYLEFT = "copyleft"
RESTRICTED = "non-commercial / source-available"
UNKNOWN = "unknown"
# Worst first: an AND expression takes the worst part, OR the best.
_SEVERITY = [COPYLEFT, RESTRICTED, UNKNOWN, WEAK_COPYLEFT, PERMISSIVE]

_RULES: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"\bBUSL|BUSINESS SOURCE|\bNC\b|-NC-|NON-?COMMERCIAL|COMMONS CLAUSE|ELASTIC"),
        RESTRICTED,
    ),
    (
        re.compile(r"\bLGPL|LESSER GENERAL|LIBRARY GENERAL|\bMPL|MOZILLA|\bEPL|ECLIPSE|\bCDDL"),
        WEAK_COPYLEFT,
    ),
    (re.compile(r"\bA?GPL|GENERAL PUBLIC|\bSSPL|SERVER SIDE PUBLIC|\bEUPL|\bOSL-"), COPYLEFT),
    (
        re.compile(
            r"MIT|\bBSD|APACHE|\bISC|0BSD|PSF|PYTHON SOFTWARE|ZLIB|UNLICENSE|\bCC0|"
            r"\bCC-BY-\d|OFL|OPEN FONT|BLUEOAK|HPND|\bWTFPL|PUBLIC DOMAIN|"
            r"UNICODE|\bX11\b|\bBSL-1\.0|BOOST"
        ),
        PERMISSIVE,
    ),
]

_CLASSIFIER_SPDX = {
    "MIT License": "MIT",
    "Apache Software License": "Apache-2.0",
    "BSD License": "BSD",
    "ISC License (ISCL)": "ISC",
    "Python Software Foundation License": "PSF-2.0",
    "Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
    "GNU Lesser General Public License v3 (LGPLv3)": "LGPL-3.0",
    "GNU Lesser General Public License v2 (LGPLv2)": "LGPL-2.0",
    "GNU Library or Lesser General Public License (LGPL)": "LGPL",
    "GNU General Public License v3 (GPLv3)": "GPL-3.0",
    "GNU General Public License v2 (GPLv2)": "GPL-2.0",
    "The Unlicense (Unlicense)": "Unlicense",
}


# Packages whose PyPI metadata names no license, checked by hand against the
# license file the published wheel ships. Used only when PyPI says nothing.
_OVERRIDES = {
    "py-rust-stemmers": "MIT",  # wheel: licenses/LICENSE (MIT, (c) 2024 qdrant)
}


@dataclass(frozen=True)
class Dep:
    name: str
    version: str
    license: str
    url: str


@dataclass
class Component:
    title: str
    deps: list[Dep] = field(default_factory=list)
    note: str = ""


# ── Classification ────────────────────────────────────────────────────────────
def _split_top(expr: str, op: str) -> list[str]:
    parts, depth, cur = [], 0, []
    tokens = re.split(r"(\(|\)|\s+)", expr)
    for tok in tokens:
        if tok == "(":
            depth += 1
        elif tok == ")":
            depth -= 1
        if depth == 0 and tok.strip().upper() == op:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(tok)
    parts.append("".join(cur))
    return [p.strip() for p in parts if p.strip()]


def _strip_parens(expr: str) -> str:
    """'(a OR b)' -> 'a OR b', but leave '(a) AND (b)' alone."""
    expr = expr.strip()
    while expr.startswith("(") and expr.endswith(")"):
        depth = 0
        for i, ch in enumerate(expr):
            depth += {"(": 1, ")": -1}.get(ch, 0)
            if depth == 0 and i < len(expr) - 1:
                return expr
        expr = expr[1:-1].strip()
    return expr


def _classify_atom(text: str) -> str:
    upper = text.upper()
    if not upper.strip() or upper.strip() in {"UNKNOWN", "NONE", "OTHER/PROPRIETARY LICENSE"}:
        return UNKNOWN
    for pattern, category in _RULES:
        if pattern.search(upper):
            return category
    return UNKNOWN


def classify(license_: str) -> str:
    """Category of an SPDX expression or free-text license name."""
    expr = _strip_parens(license_ or "")
    ands = _split_top(expr, "AND")
    if len(ands) > 1:
        return min((classify(p) for p in ands), key=_SEVERITY.index)
    ors = _split_top(expr, "OR")
    if len(ors) > 1:
        return max((classify(p) for p in ors), key=_SEVERITY.index)
    return _classify_atom(expr)


def needs_review(dep: Dep) -> bool:
    return classify(dep.license) != PERMISSIVE


# ── Parsers ───────────────────────────────────────────────────────────────────
def parse_uv_export(text: str) -> list[tuple[str, str]]:
    out = []
    for line in text.splitlines():
        line = line.split(";", 1)[0].strip()
        m = re.fullmatch(r"([A-Za-z0-9._-]+)(?:\[[^\]]*\])?==(\S+)", line)
        if m:
            out.append((m.group(1).lower(), m.group(2)))
    return out


def pypi_license(info: dict, name: str = "") -> str:
    """License expression > short license field > trove classifiers (several =
    a choice) > a verified override for packages that publish no metadata."""
    expr = (info.get("license_expression") or "").strip()
    if expr:
        return expr
    short = (info.get("license") or "").strip()
    if short and len(short) <= 60 and "\n" not in short and classify(short) != UNKNOWN:
        return short
    classifiers = [
        _CLASSIFIER_SPDX.get(c.rsplit(" :: ", 1)[-1], c.rsplit(" :: ", 1)[-1])
        for c in info.get("classifiers") or []
        if c.startswith("License :: ")
    ]
    if classifiers:
        return " OR ".join(dict.fromkeys(classifiers))
    return _OVERRIDES.get(name, short if len(short) <= 60 else "")


def _pypi_url(info: dict) -> str:
    urls = info.get("project_urls") or {}
    for key in ("Source", "Source Code", "Repository", "Homepage", "homepage"):
        if urls.get(key):
            return urls[key]
    return info.get("home_page") or info.get("package_url") or ""


def parse_go_report(report: str, versions: dict[str, str]) -> list[Dep]:
    deps: dict[str, Dep] = {}
    for row in csv.reader(io.StringIO(report)):
        if len(row) < 3:
            continue
        pkg, url, license_ = row[0], row[1], row[2]
        module = max(
            (m for m in versions if pkg == m or pkg.startswith(m + "/")), key=len, default=pkg
        )
        deps.setdefault(module, Dep(module, versions.get(module, ""), license_, url))
    return sorted(deps.values(), key=lambda d: d.name)


def parse_pnpm(text: str) -> list[Dep]:
    deps = []
    for license_, pkgs in json.loads(text).items():
        for pkg in pkgs:
            name = pkg["name"]
            url = pkg.get("homepage") or f"https://www.npmjs.com/package/{name}"
            for version in pkg.get("versions") or [""]:
                deps.append(Dep(name, version, license_, url))
    return sorted(deps, key=lambda d: (d.name, d.version))


def license_from_text(text: str) -> str:
    upper = text[:2000].upper()
    if "SIL OPEN FONT LICENSE" in upper:
        return "OFL-1.1"
    if "APACHE LICENSE" in upper and "VERSION 2.0" in upper:
        return "Apache-2.0"
    if "MIT LICENSE" in upper or "PERMISSION IS HEREBY GRANTED, FREE OF CHARGE" in upper:
        return "MIT"
    return ""


_MODEL_LINK = re.compile(r"\[`?([^`\]]+)`?\]\((https?://[^)]+)\)")
_REVISION = re.compile(r"@([0-9a-f]{6,40})")


def parse_models(markdown: str) -> list[Dep]:
    """Default (✅) rows of MODELS.md: | role | [model](url) | weights@rev | license | default |

    Only defaults are baked into release images. Opt-in models are downloaded by
    the operator, so Raggie does not distribute them and they are not listed.
    """
    deps = []
    for line in markdown.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 5 or not (link := _MODEL_LINK.search(cells[1])):
            continue
        if "✅" not in cells[4]:
            continue
        rev = _REVISION.search(cells[2])
        license_ = re.sub(r"\s*\(.*\)$", "", cells[3].replace("*", "")).strip()
        deps.append(Dep(link.group(1), rev.group(1) if rev else "", license_, link.group(2)))
    return deps


# ── Collectors (need tools + network) ─────────────────────────────────────────
def _run(cmd: list[str], cwd: Path, env: dict | None = None) -> str:
    return subprocess.run(
        cmd,
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
    ).stdout


def go_component(root: Path, module_dir: str, tool: Path) -> Component:
    cwd = root / module_dir
    versions = dict(
        line.split(" ", 1)
        for line in _run(
            ["go", "list", "-m", "-f", "{{.Path}} {{.Version}}", "all"], cwd
        ).splitlines()
        if " " in line
    )
    report = _run([str(tool), "report", "./...", "--ignore", FIRST_PARTY_GO], cwd, _go_env(cwd))
    return Component(f"Go — {module_dir}", parse_go_report(report, versions))


def _go_env(module_dir: Path) -> dict[str, str]:
    # go-licenses must be built and run with the module's toolchain, otherwise
    # it mistakes the standard library for unversioned third-party packages.
    toolchain = re.search(r"^toolchain (\S+)", (module_dir / "go.mod").read_text(), re.M)
    return {"GOTOOLCHAIN": toolchain.group(1)} if toolchain else {}


def build_go_licenses(root: Path, bindir: Path) -> Path:
    bindir.mkdir(parents=True, exist_ok=True)
    _run(
        ["go", "install", GO_LICENSES],
        bindir,
        {"GOBIN": str(bindir), **_go_env(root / GO_MODULES[0])},
    )
    return bindir / "go-licenses"


def _fetch_pypi(dep: tuple[str, str]) -> Dep:
    name, version = dep
    try:
        with urllib.request.urlopen(PYPI.format(name=name, version=version), timeout=20) as r:
            info = json.load(r)["info"]
    except (urllib.error.URLError, TimeoutError, KeyError, ValueError):
        return Dep(name, version, _OVERRIDES.get(name, ""), f"https://pypi.org/project/{name}/")
    return Dep(
        name,
        version,
        pypi_license(info, name),
        _pypi_url(info) or f"https://pypi.org/project/{name}/",
    )


def python_component(root: Path, project: str, pool: ThreadPoolExecutor) -> Component:
    text = _run(
        [
            "uv",
            "export",
            "--frozen",
            "--no-dev",
            "--no-hashes",
            "--no-emit-project",
            "--no-header",
            "--no-annotate",
        ],
        root / project,
    )
    deps = list(pool.map(_fetch_pypi, sorted(set(parse_uv_export(text)))))
    return Component(f"Python — {project}", deps)


def npm_component(root: Path) -> Component:
    text = _run(["pnpm", "licenses", "list", "--prod", "--json"], root / WEB)
    return Component(
        "npm — web (production dependencies)",
        parse_pnpm(text),
        note="Platform-specific optional packages reflect the machine that generated "
        "this file; the release image is linux/musl.",
    )


def assets_component(root: Path) -> Component:
    deps = []
    for ofl in sorted((root / WEB / "app" / "fonts").glob("*/OFL.txt")):
        deps.append(
            Dep(
                ofl.parent.name,
                "",
                license_from_text(ofl.read_text("utf-8")),
                str(ofl.relative_to(root)),
            )
        )
    for lic in sorted((root / WEB / "public" / "fonts").glob("*LICENSE*")):
        name = lic.name.split(".LICENSE")[0]
        deps.append(
            Dep(name, "", license_from_text(lic.read_text("utf-8")), str(lic.relative_to(root)))
        )
    return Component("Fonts and icons (web)", deps)


def models_component(root: Path) -> Component:
    return Component(
        "Models (MODELS.md)",
        parse_models((root / "MODELS.md").read_text("utf-8")),
        note="Models baked into release images. Opt-in models (see MODELS.md) are not distributed.",
    )


# ── Rendering ─────────────────────────────────────────────────────────────────
def _cell(value: str) -> str:
    return " ".join(value.split()).replace("|", "\\|")


def render(components: list[Component]) -> str:
    lines = [
        "# Third-party notices",
        "",
        "<!-- Generated by scripts/notices/gen_third_party.py (`make notices`). "
        "Do not edit by hand. -->",
        "",
        "Raggie itself is licensed under the Apache License 2.0 (see LICENSE and NOTICE). "
        "It ships or downloads the third-party components below, each under its own "
        "license.",
        "",
        "## Review required",
        "",
    ]
    review = [(c, d) for c in components for d in c.deps if needs_review(d)]
    if review:
        lines += [
            "Copyleft, non-commercial or unidentified licenses — check how each one "
            "is used and shipped before a release.",
            "",
            "| Component | Package | Version | License | Category |",
            "|---|---|---|---|---|",
        ]
        lines += [
            f"| {_cell(c.title)} | {_cell(d.name)} | {_cell(d.version)} | "
            f"{_cell(d.license or 'UNKNOWN')} | {classify(d.license)} |"
            for c, d in review
        ]
    else:
        lines.append("None.")
    for comp in components:
        lines += ["", f"## {comp.title}", ""]
        if comp.note:
            lines += [comp.note, ""]
        lines += ["| Package | Version | License | URL |", "|---|---|---|---|"]
        lines += [
            f"| {_cell(d.name)} | {_cell(d.version)} | {_cell(d.license or 'UNKNOWN')} "
            f"| {_cell(d.url)} |"
            for d in comp.deps
        ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", default="THIRD_PARTY_NOTICES.md")
    parser.add_argument("--bindir", help="where to build go-licenses (default: a temp dir)")
    args = parser.parse_args(argv)
    root = Path(_run(["git", "rev-parse", "--show-toplevel"], Path.cwd()).strip())
    with tempfile.TemporaryDirectory() as tmp, ThreadPoolExecutor(max_workers=4) as pool:
        tool = build_go_licenses(root, Path(args.bindir or tmp))
        components = [go_component(root, m, tool) for m in GO_MODULES]
        components += [python_component(root, p, pool) for p in PY_PROJECTS]
        components += [npm_component(root), assets_component(root), models_component(root)]
    out = root / args.output
    out.write_text(render(components), encoding="utf-8")
    flagged = sum(needs_review(d) for c in components for d in c.deps)
    print(
        f"wrote {out.relative_to(root)}: {sum(len(c.deps) for c in components)} entries, "
        f"{flagged} need review",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
