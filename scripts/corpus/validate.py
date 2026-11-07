# SPDX-License-Identifier: Apache-2.0
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pdfplumber==0.11.10",
#     "pypdfium2==5.14.0",
#     "python-docx==1.2.0",
#     "openpyxl==3.1.5",
#     "python-pptx==1.0.2",
#     "pillow==12.3.0",
#     "pytesseract==0.3.13",
#     "pyyaml==6.0.3",
# ]
# ///
"""Validate the golden set against the corpus text the workers actually extract.

    uv run scripts/corpus/validate.py
    uv run scripts/corpus/validate.py --golden examples/golden/golden.yaml --dump /tmp/text

Text comes from the ingestion worker's own parser
(services/workers/raggie_workers/ingestion/parsing.py, loaded from this repo).
The scanned PNG needs a local Tesseract (tur+eng) for real OCR. Without it the
image's quotes are checked against the generator's source text for that image
(content/*.py) and the run prints that OCR fidelity was NOT verified. No Docker,
no system packages: plain Python via uv.

Checks: schema and unique ids; every expected document exists; every evidence
quote appears in its document's extracted text; every answer (each '; '-separated
part) appears in the evidence; unanswerable questions have no answer/documents
and their `absent_terms` appear nowhere in the corpus; every corpus document is
targeted by at least one question. Matching normalizes Unicode (NFC), table
cell separators ('|') and whitespace; answer matching is also case-insensitive.
"""

from __future__ import annotations

import argparse
import collections
import importlib.util
import json
import sys
import unicodedata
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
CORPUS = REPO / "examples" / "sample-corpus"
GOLDEN = REPO / "examples" / "golden" / "golden.yaml"
PARSING = REPO / "services" / "workers" / "raggie_workers" / "ingestion" / "parsing.py"
SKIP = {"README.md"}

TYPES = {
    "single-fact",
    "table-lookup",
    "multi-hop",
    "temporal/version",
    "negative/unanswerable",
    "ocr",
}
LANGS = {"tr", "en"}
DIFFICULTIES = {"easy", "medium", "hard"}
REQUIRED = (
    "id",
    "question",
    "language",
    "answer",
    "expected_documents",
    "evidence",
    "type",
    "difficulty",
)


def norm(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\\|", " ").replace("|", " ")
    return " ".join(text.split())


def load_parser():
    spec = importlib.util.spec_from_file_location("raggie_parsing", PARSING)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module  # dataclasses resolve their module by name
    spec.loader.exec_module(module)
    return module


IMAGE_EXTS = {".png", ".jpg", ".jpeg"}


def image_source_texts() -> dict[str, str]:
    """What each generated image renders (title, meta lines, paragraphs), taken
    from the content modules — the fallback when Tesseract is unavailable."""
    sys.path.insert(0, str(HERE))
    from content import load_docs
    from renderers import COMPANY_CAPS, _meta_lines

    out: dict[str, str] = {}
    for doc in load_docs():
        if doc.ext not in IMAGE_EXTS:
            continue
        lines = [COMPANY_CAPS, doc.title]
        lines += [f"{k}: {v}" for k, v in _meta_lines(doc)]
        for block in doc.blocks:
            text = getattr(block, "text", None)
            lines += [text] if text else list(getattr(block, "items", ()))
        out[doc.name] = "\n".join(lines)
    return out


def extract_corpus(corpus: Path) -> tuple[dict[str, str], dict[str, str], list[str]]:
    parser = load_parser()
    texts: dict[str, str] = {}
    paths: dict[str, str] = {}
    unverified_ocr: list[str] = []
    sources: dict[str, str] | None = None
    for path in sorted(p for p in corpus.rglob("*") if p.is_file()):
        if path.name in SKIP or path.name.startswith("."):
            continue
        if path.name in texts:
            raise SystemExit(f"duplicate corpus file name: {path.name}")
        text = parser.extract_text_from_path(path.name, str(path))
        if path.suffix.lower() in IMAGE_EXTS and not text.strip():
            # The worker's OCR is best-effort and yields "" without Tesseract.
            sources = image_source_texts() if sources is None else sources
            if path.name not in sources:
                raise SystemExit(
                    f"{path.name}: no OCR text and no generator source to fall back to"
                )
            text = sources[path.name]
            unverified_ocr.append(path.name)
        texts[path.name] = text
        paths[path.name] = str(path.relative_to(corpus))
    return texts, paths, unverified_ocr


def load_golden(source: Path) -> list[dict]:
    files = sorted(source.glob("*.yaml")) if source.is_dir() else [source]
    questions: list[dict] = []
    for f in files:
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        items = data.get("questions", []) if isinstance(data, dict) else data
        for q in items or []:
            q.setdefault("_file", f.name)
            questions.append(q)
    return questions


def answer_parts(answer) -> list[str]:
    return [part.strip() for part in str(answer).split("; ") if part.strip()]


def validate(questions: list[dict], texts: dict[str, str]) -> list[str]:
    errors: list[str] = []
    normed = {name: norm(text) for name, text in texts.items()}
    lowered = {name: text.casefold() for name, text in normed.items()}
    seen: set[str] = set()
    for q in questions:
        qid = q.get("id", "<no id>")
        where = f"{qid} ({q.get('_file')})"
        missing = [k for k in REQUIRED if k not in q]
        if missing:
            errors.append(f"{where}: missing fields {missing}")
            continue
        if qid in seen:
            errors.append(f"{where}: duplicate id")
        seen.add(qid)
        if q["type"] not in TYPES:
            errors.append(f"{where}: unknown type {q['type']!r}")
        if q["language"] not in LANGS:
            errors.append(f"{where}: unknown language {q['language']!r}")
        if q["difficulty"] not in DIFFICULTIES:
            errors.append(f"{where}: unknown difficulty {q['difficulty']!r}")
        docs = q["expected_documents"] or []
        evidence = q["evidence"] or []
        for d in docs:
            if d not in texts:
                errors.append(f"{where}: expected document not in corpus: {d}")

        if q["answer"] is None:
            if q["type"] != "negative/unanswerable":
                errors.append(f"{where}: answer is null but type is {q['type']}")
            if docs or evidence:
                errors.append(f"{where}: unanswerable question lists documents/evidence")
            for term in q.get("absent_terms") or []:
                hits = [n for n, t in lowered.items() if norm(term).casefold() in t]
                if hits:
                    errors.append(f"{where}: absent term {term!r} found in {hits}")
            continue

        if q["type"] == "negative/unanswerable":
            errors.append(f"{where}: negative question must have answer: null")
        if not docs or not evidence:
            errors.append(f"{where}: answerable question needs documents and evidence")
            continue
        quotes: list[str] = []
        for ev in evidence:
            doc, quote = ev.get("document"), ev.get("quote")
            if doc not in docs:
                errors.append(f"{where}: evidence document {doc} not in expected_documents")
            if doc not in normed or not quote:
                continue
            if norm(quote) not in normed[doc]:
                errors.append(f"{where}: quote not found in {doc}: {quote!r}")
            quotes.append(norm(quote).casefold())
        cited = {ev.get("document") for ev in evidence}
        for d in docs:
            if d not in cited:
                errors.append(f"{where}: expected document {d} has no evidence quote")
        joined = " \n ".join(quotes)
        for part in answer_parts(q["answer"]):
            if norm(part).casefold() not in joined:
                errors.append(f"{where}: answer part {part!r} not in evidence")
    return errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="validate golden set against the corpus")
    ap.add_argument("--golden", type=Path, default=GOLDEN, help="golden YAML file or directory")
    ap.add_argument("--corpus", type=Path, default=CORPUS)
    ap.add_argument("--dump", type=Path, help="write each document's extracted text here")
    ap.add_argument("--only", default="", help="comma-separated folders: skip coverage of others")
    args = ap.parse_args(argv)

    texts, paths, unverified_ocr = extract_corpus(args.corpus)
    if args.dump:
        args.dump.mkdir(parents=True, exist_ok=True)
        for name, text in texts.items():
            (args.dump / f"{name}.txt").write_text(text, encoding="utf-8")
    questions = load_golden(args.golden)
    errors = validate(questions, texts)

    only = {f.strip() for f in args.only.split(",") if f.strip()}
    targeted = {d for q in questions for d in (q.get("expected_documents") or [])}
    for name, rel in paths.items():
        if only and rel.split("/")[0] not in only:
            continue
        if name not in targeted:
            errors.append(f"coverage: no question targets {rel}")

    by_type = collections.Counter(q.get("type") for q in questions)
    by_lang = collections.Counter(q.get("language") for q in questions)
    by_diff = collections.Counter(q.get("difficulty") for q in questions)
    chars = sum(len(t) for t in texts.values())
    print(f"corpus: {len(texts)} documents, {chars:,} extracted chars")
    print(f"golden: {len(questions)} questions")
    print(f"  by type: {json.dumps(dict(sorted(by_type.items())), ensure_ascii=False)}")
    print(f"  by language: {json.dumps(dict(sorted(by_lang.items())))}")
    print(f"  by difficulty: {json.dumps(dict(sorted(by_diff.items())))}")
    if unverified_ocr:
        print(
            f"NOTE: Tesseract not available — OCR NOT verified for {', '.join(unverified_ocr)}; "
            "their quotes were checked against the generator source text instead "
            "(install tesseract with tur+eng to verify real OCR output)"
        )
    if errors:
        print(f"\nFAILED: {len(errors)} problem(s)")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: every evidence quote and answer verified against extracted text")
    return 0


if __name__ == "__main__":
    sys.exit(main())
