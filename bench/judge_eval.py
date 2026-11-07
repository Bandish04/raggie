# SPDX-License-Identifier: Apache-2.0
"""Faithfulness-judge benchmark: run the eval worker's real judge over a labeled set.

    make eval-judge ARGS=--dry-run       # validate the dataset only, no model call
    make eval-judge                      # score every item against LLMAAS_*
    make eval-judge ARGS="--limit 10"    # quick smoke against a real endpoint

The judge, its prompt and its context flattening are imported from
services/workers (raggie_workers.evaluation), so the numbers describe exactly what
production runs. Settings come from the same environment variables as the eval
worker: LLMAAS_BASE_URL, LLMAAS_API_KEY, LLMAAS_CHAT_MODEL,
EVAL_FAITHFULNESS_THRESHOLD, EVAL_LLM_TIMEOUT_SECONDS, EVAL_MAX_CONCURRENCY.
Set JUDGE_EVAL_HARDWARE to describe where the model runs (it goes in the report).

The positive class is "unfaithful": an item is flagged when its score is below the
threshold, the same rule the eval worker applies. Items the judge could not score
(timeouts, unparsable replies, HTTP errors) are reported separately and excluded
from the metrics.

Writes docs/benchmarks/judge-eval-<YYYY-MM-DD>.md plus a .json with every score;
a second run on the same day gets a -2 suffix, and nothing is overwritten.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import importlib
import json
import os
import platform
import subprocess
import sys
import time
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse

import yaml

REPO = Path(__file__).resolve().parent.parent
DATASET = REPO / "examples" / "judge-eval" / "judge_eval.yaml"
CORPUS_DIR = REPO / "examples" / "sample-corpus"
CORPUS_SOURCE = REPO / "scripts" / "corpus"
RESULTS_DIR = REPO / "docs" / "benchmarks"

LANGUAGES = ("tr", "en")
LABELS = ("faithful", "unfaithful")
ERROR_TYPES = ("wrong_number", "wrong_entity", "unsupported_claim", "contradiction", "partial")
TAGS = ("paraphrase", "unit_format", "multi_passage", "distractor")
SWEEP = tuple(round(t / 20, 2) for t in range(1, 20))  # 0.05 .. 0.95


# ── Dataset ──────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class CorpusDoc:
    lang: str
    text: str  # normalized


def normalize(text: str) -> str:
    """NFC plus collapsed whitespace: passages may be re-wrapped, never reworded."""
    return " ".join(unicodedata.normalize("NFC", text).split())


def load_dataset(path: Path = DATASET) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def corpus_index() -> dict[str, CorpusDoc]:
    """Every corpus document by file name, with its full text from the generator
    source (scripts/corpus/content). build.py renders that text verbatim into the
    PDF/DOCX/XLSX/PPTX/MD files, and scripts/corpus/validate.py checks the
    extraction against it. Only documents present on disk are indexed."""
    on_disk = {p.name for p in CORPUS_DIR.rglob("*") if p.is_file()}
    sys.path.insert(0, str(CORPUS_SOURCE))
    try:
        content = importlib.import_module("content")
        docs = content.load_docs()
    finally:
        sys.path.remove(str(CORPUS_SOURCE))
        # The generator's modules have generic names ("content", "model"); drop them.
        for name in [
            m for m in sys.modules if m in ("content", "model") or m.startswith("content.")
        ]:
            del sys.modules[name]
    return {
        d.name: CorpusDoc(d.lang, normalize(" ".join(_doc_strings(d))))
        for d in docs
        if d.name in on_disk
    }


def _doc_strings(doc) -> list[str]:
    out = [doc.title, doc.subtitle, *(v for _, v in doc.meta)]
    for block in doc.blocks:
        out += _block_strings(block)
    for sheet in doc.sheets:
        out += [sheet.title, *sheet.header, *sheet.notes]
        out += [str(c) for row in sheet.rows for c in row]
    for slide in doc.slides:
        out += [slide.title, slide.subtitle, *slide.bullets, slide.notes]
        if slide.table is not None:
            out += _block_strings(slide.table)
    return [s for s in out if s]


def _block_strings(block) -> list[str]:
    if hasattr(block, "items"):  # Bullets
        return list(block.items)
    if hasattr(block, "rows"):  # Table
        return [block.caption, *block.header, *(c for row in block.rows for c in row)]
    text = getattr(block, "text", "")
    return [text] if text else []


def validate_dataset(data: dict, corpus: dict[str, CorpusDoc]) -> list[str]:
    """Schema and support checks; returns human-readable errors (empty = valid)."""
    errors: list[str] = []
    if not isinstance(data, dict) or data.get("version") != 1:
        return ["dataset: expected a mapping with version: 1"]
    items = data.get("items")
    if not isinstance(items, list) or not items:
        return ["dataset: 'items' must be a non-empty list"]
    seen: set[str] = set()
    for n, item in enumerate(items):
        iid = item.get("id") if isinstance(item, dict) else None
        where = f"item {iid or f'#{n}'}"
        if not isinstance(item, dict) or not iid:
            errors.append(f"{where}: needs an id")
            continue
        if iid in seen:
            errors.append(f"{where}: duplicate id")
        seen.add(iid)
        lang, label, error_type = item.get("language"), item.get("label"), item.get("error_type")
        if lang not in LANGUAGES:
            errors.append(f"{where}: language must be one of {LANGUAGES}")
        if label not in LABELS:
            errors.append(f"{where}: label must be one of {LABELS}")
        if label == "faithful" and error_type is not None:
            errors.append(f"{where}: faithful items take no error_type")
        if label == "unfaithful" and error_type not in ERROR_TYPES:
            errors.append(f"{where}: unfaithful items need an error_type in {ERROR_TYPES}")
        if not str(item.get("answer") or "").strip():
            errors.append(f"{where}: answer is empty")
        errors += [f"{where}: unknown tag {t!r}" for t in item.get("tags") or () if t not in TAGS]
        context = item.get("context")
        if not isinstance(context, list) or not 1 <= len(context) <= 3:
            errors.append(f"{where}: context must hold 1-3 passages")
            continue
        for passage in context:
            name = passage.get("document") if isinstance(passage, dict) else None
            text = normalize(str(passage.get("passage") or "")) if name else ""
            doc = corpus.get(name)
            if doc is None:
                errors.append(f"{where}: unknown document {name!r}")
            elif not text or text not in doc.text:
                errors.append(f"{where}: passage not found verbatim in {name}: {text[:60]!r}")
            elif lang in LANGUAGES and doc.lang != lang:
                errors.append(f"{where}: document {name} is {doc.lang}, item is {lang}")
    return errors


# ── Scoring ──────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Result:
    id: str
    language: str
    label: str
    error_type: str | None
    score: float | None
    status: str  # scored | unscored (judge returned None) | error (call raised)
    seconds: float = 0.0


async def run_judge(items: list[dict], judge, *, concurrency: int = 4) -> list[Result]:
    """Score every item with `judge` (anything with `async score(answer, context)`).
    The context is flattened exactly as the eval worker does for a real answer."""
    from raggie_workers.evaluation.store import context_from_sources

    gate = asyncio.Semaphore(concurrency)

    async def one(item: dict) -> Result:
        context = context_from_sources([{"text": p["passage"]} for p in item["context"]])
        start = time.perf_counter()
        async with gate:
            try:
                score = await judge.score(item["answer"], context)
                status = "scored" if score is not None else "unscored"
            except Exception as exc:  # noqa: BLE001 — one failed call must not end the run
                print(f"  {item['id']}: judge call failed: {exc}", file=sys.stderr)
                score, status = None, "error"
        return Result(
            item["id"],
            item["language"],
            item["label"],
            item.get("error_type"),
            score,
            status,
            round(time.perf_counter() - start, 3),
        )

    return list(await asyncio.gather(*(one(i) for i in items)))


@dataclass(frozen=True)
class Metrics:
    threshold: float
    tp: int
    fp: int
    fn: int
    tn: int

    @property
    def n(self) -> int:
        return self.tp + self.fp + self.fn + self.tn

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0

    @property
    def accuracy(self) -> float:
        return (self.tp + self.tn) / self.n if self.n else 0.0


def _scored(results: list[Result]) -> list[Result]:
    return [r for r in results if r.score is not None]


def metrics_at(results: list[Result], threshold: float) -> Metrics:
    tp = fp = fn = tn = 0
    for r in _scored(results):
        flagged = r.score < threshold  # the eval worker's rule
        if r.label == "unfaithful":
            tp, fn = (tp + 1, fn) if flagged else (tp, fn + 1)
        else:
            fp, tn = (fp + 1, tn) if flagged else (fp, tn + 1)
    return Metrics(threshold, tp, fp, fn, tn)


def roc_auc(results: list[Result]) -> float | None:
    """Probability that an unfaithful item scores below a faithful one (ties 0.5)."""
    scored = _scored(results)
    bad = [r.score for r in scored if r.label == "unfaithful"]
    good = [r.score for r in scored if r.label == "faithful"]
    if not bad or not good:
        return None
    wins = sum(1.0 if b < g else 0.5 if b == g else 0.0 for b in bad for g in good)
    return wins / (len(bad) * len(good))


def sweep(results: list[Result], thresholds=SWEEP) -> list[Metrics]:
    return [metrics_at(results, t) for t in thresholds]


def best_f1(rows: list[Metrics]) -> Metrics:
    return max(rows, key=lambda m: (m.f1, -abs(m.threshold - 0.5)))


def breakdown(results: list[Result], threshold: float, key: str) -> dict[str, Metrics]:
    groups = sorted({getattr(r, key) for r in results})
    return {g: metrics_at([r for r in results if getattr(r, key) == g], threshold) for g in groups}


def detection_by_error_type(results: list[Result], threshold: float) -> dict[str, tuple]:
    """(flagged, scored) unfaithful items per error type."""
    out: dict[str, tuple[int, int]] = {}
    for r in _scored(results):
        if r.label == "unfaithful":
            hit, total = out.get(r.error_type, (0, 0))
            out[r.error_type] = (hit + (r.score < threshold), total + 1)
    return dict(sorted(out.items()))


def not_scored(results: list[Result]) -> dict[str, int]:
    return dict(Counter(r.status for r in results if r.score is None))


# ── Report ───────────────────────────────────────────────────────────────────
def _row(name: str, m: Metrics) -> str:
    return (
        f"| {name} | {m.n} | {m.tp} | {m.fp} | {m.fn} | {m.tn} | {m.precision:.3f} "
        f"| {m.recall:.3f} | {m.f1:.3f} | {m.accuracy:.3f} |"
    )


_HEAD = (
    "| | n | TP | FP | FN | TN | precision | recall | F1 | accuracy |\n"
    "|---|---|---|---|---|---|---|---|---|---|"
)


def render_report(results: list[Result], *, threshold: float, meta: dict) -> str:
    at = metrics_at(results, threshold)
    rows = sweep(results)
    best = best_f1(rows)
    auc = roc_auc(results)
    missing = not_scored(results)
    seconds = sorted(r.seconds for r in results if r.status == "scored")
    p50 = seconds[len(seconds) // 2] if seconds else 0.0
    p95 = seconds[min(len(seconds) - 1, int(len(seconds) * 0.95))] if seconds else 0.0
    labels = Counter(r.label for r in results)
    lines = [
        "# Faithfulness judge benchmark",
        "",
        f"- Date: {meta['date']}",
        f"- Judge model: `{meta['model']}` at `{meta['endpoint']}`",
        f"- Model hardware: {meta['hardware']}",
        f"- Client: {meta['client']} · revision `{meta['revision']}`",
        f"- Dataset: `{meta['dataset']}` ({len(results)} items: "
        f"{labels['faithful']} faithful, {labels['unfaithful']} unfaithful)",
        f"- Positive class: unfaithful (flagged when score < threshold). "
        f"Threshold: {threshold} (EVAL_FAITHFULNESS_THRESHOLD)",
        f"- Not scored: {sum(missing.values())}"
        + (f" ({', '.join(f'{k}: {v}' for k, v in sorted(missing.items()))})" if missing else "")
        + " — excluded from every metric below",
        f"- Judge latency per item: p50 {p50:.2f} s, p95 {p95:.2f} s",
        "",
        "## At the configured threshold",
        "",
        _HEAD,
        _row(f"all @ {threshold}", at),
        "",
        f"ROC-AUC (unfaithful scored below faithful): "
        f"{f'{auc:.3f}' if auc is not None else 'n/a (one class only)'}",
        "",
        f"Best F1 in the sweep: {best.f1:.3f} at threshold {best.threshold}.",
        "",
        "## By language",
        "",
        _HEAD,
        *(_row(lang, m) for lang, m in breakdown(results, threshold, "language").items()),
        "",
        "## Detection by error type (unfaithful items flagged)",
        "",
        "| error type | flagged | scored | detection rate |",
        "|---|---|---|---|",
        *(
            f"| {t} | {hit} | {total} | {hit / total:.3f} |"
            for t, (hit, total) in detection_by_error_type(results, threshold).items()
        ),
        "",
        "## Threshold sweep",
        "",
        _HEAD,
        *(_row(str(m.threshold), m) for m in rows),
        "",
    ]
    return "\n".join(lines)


# ── CLI ──────────────────────────────────────────────────────────────────────
def _revision() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _result_path(date: str) -> Path:
    base = RESULTS_DIR / f"judge-eval-{date}"
    path, n = base.with_suffix(".md"), 1
    while path.exists():
        n += 1
        path = RESULTS_DIR / f"judge-eval-{date}-{n}.md"
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate the dataset and its corpus links; no model call",
    )
    parser.add_argument("--limit", type=int, default=0, help="score only the first N items")
    parser.add_argument(
        "--threshold", type=float, default=None, help="override EVAL_FAITHFULNESS_THRESHOLD"
    )
    args = parser.parse_args(argv)

    data = load_dataset(args.dataset)
    errors = validate_dataset(data, corpus_index())
    items = data["items"]
    for line in errors:
        print(f"ERROR {line}", file=sys.stderr)
    counts = Counter((i.get("language"), i.get("label")) for i in items)
    print(
        f"{args.dataset}: {len(items)} items, "
        + ", ".join(f"{lang}/{label}: {n}" for (lang, label), n in sorted(counts.items()))
    )
    if errors:
        return 1
    if args.dry_run:
        print("dataset OK (dry run: no judge called)")
        return 0

    from raggie_workers.config import Settings
    from raggie_workers.evaluation.judge import FaithfulnessJudge

    cfg = Settings()
    threshold = args.threshold if args.threshold is not None else cfg.eval_faithfulness_threshold
    judge = FaithfulnessJudge(
        base_url=cfg.llmaas_base_url,
        api_key=cfg.llmaas_api_key,
        model=cfg.llmaas_chat_model,
        max_concurrency=cfg.eval_max_concurrency,
        timeout=cfg.eval_llm_timeout_seconds,
    )
    if args.limit:
        items = items[: args.limit]
    print(f"scoring {len(items)} items with {cfg.llmaas_chat_model} ...")
    results = asyncio.run(run_judge(items, judge, concurrency=cfg.eval_max_concurrency))

    date = dt.date.today().isoformat()
    meta = {
        "date": date,
        "model": cfg.llmaas_chat_model,
        "endpoint": urlparse(cfg.llmaas_base_url).netloc or cfg.llmaas_base_url,
        "hardware": os.environ.get("JUDGE_EVAL_HARDWARE") or "not stated (set JUDGE_EVAL_HARDWARE)",
        "client": f"{platform.system()} {platform.machine()}, Python {platform.python_version()}",
        "revision": _revision(),
        "dataset": str(args.dataset.resolve().relative_to(REPO))
        if args.dataset.resolve().is_relative_to(REPO)
        else str(args.dataset),
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = _result_path(date)
    path.write_text(render_report(results, threshold=threshold, meta=meta), encoding="utf-8")
    path.with_suffix(".json").write_text(
        json.dumps(
            {"meta": meta, "threshold": threshold, "results": [asdict(r) for r in results]},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    at = metrics_at(results, threshold)
    print(
        f"wrote {path.relative_to(REPO)}: precision {at.precision:.3f}, recall "
        f"{at.recall:.3f}, F1 {at.f1:.3f}, not scored {sum(not_scored(results).values())}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
