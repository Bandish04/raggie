# SPDX-License-Identifier: Apache-2.0

"""Reranker benchmark gate (quality, latency, memory) for the local cross-encoder.

    python scripts/bench_rerank.py                      # default candidates vs jina-v2
    python scripts/bench_rerank.py --models BAAI/bge-reranker-v2-m3 --threads 4

Each model runs in its own subprocess (clean RSS) through the same code path the
gateway uses (pinned snapshot + fastembed TextCrossEncoder). Measured:
  - nDCG@10 on bench/rerank_tr_en.json (synthetic TR+EN, graded relevance,
    24 candidates per query incl. same-topic hard negatives);
  - p95 latency of one rerank call with 24 documents x 1500 characters;
  - peak RSS of the process.

Gate for a candidate (baseline = jinaai/jina-reranker-v2-base-multilingual):
  nDCG@10 >= baseline - 0.02, p95 <= 1.5 s (OMP/intra-op threads = 4),
  RSS <= 1.5 GB. Exit code 1 when the first candidate (the default) fails.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import resource
import statistics
import subprocess
import sys
import time
from pathlib import Path

BASELINE = "jinaai/jina-reranker-v2-base-multilingual"
CANDIDATES = ["Alibaba-NLP/gte-multilingual-reranker-base", "BAAI/bge-reranker-v2-m3"]
DATASET = Path(__file__).resolve().parents[1] / "bench" / "rerank_tr_en.json"
CANDIDATES_PER_QUERY = 24
LATENCY_DOC_CHARS = 1500
NDCG_GATE_DELTA = 0.02
P95_GATE_SECONDS = 1.5
RSS_GATE_BYTES = int(1.5 * 1024**3)


def load_queries(path: Path) -> list[dict]:
    """Expand the dataset into queries with their 24 candidate passages."""
    data = json.loads(path.read_text(encoding="utf-8"))
    pools: dict[str, list[tuple[str, str, str]]] = {}
    for topic in data["topics"]:
        for pid, text in topic["passages"].items():
            pools.setdefault(topic["lang"], []).append((topic["id"], pid, text))
    queries = []
    for topic in data["topics"]:
        pool = pools[topic["lang"]]
        own = [(pid, text) for tid, pid, text in pool if tid == topic["id"]]
        others = [(pid, text) for tid, pid, text in pool if tid != topic["id"]]
        for n, query in enumerate(topic["queries"]):
            rng = random.Random(f"{topic['id']}:{n}")
            picks = rng.sample(others, min(len(others), CANDIDATES_PER_QUERY - len(own)))
            candidates = own + picks
            rng.shuffle(candidates)  # no positional hint
            queries.append(
                {
                    "lang": topic["lang"],
                    "query": query["q"],
                    "docs": [text for _, text in candidates],
                    "rels": [query["rel"].get(pid, 0) for pid, _ in candidates],
                }
            )
    return queries


def ndcg_at_k(scores: list[float], rels: list[int], k: int = 10) -> float:
    order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:k]
    dcg = sum((2 ** rels[i] - 1) / math.log2(rank + 2) for rank, i in enumerate(order))
    ideal = sorted(rels, reverse=True)[:k]
    idcg = sum((2**r - 1) / math.log2(rank + 2) for rank, r in enumerate(ideal))
    return dcg / idcg if idcg else 0.0


def latency_docs(queries: list[dict]) -> list[str]:
    """24 documents of exactly LATENCY_DOC_CHARS characters (realistic text)."""
    texts = [doc for q in queries for doc in q["docs"]]
    docs = []
    for i in range(CANDIDATES_PER_QUERY):
        buf, j = "", i
        while len(buf) < LATENCY_DOC_CHARS:
            buf += texts[j % len(texts)] + " "
            j += 7
        docs.append(buf[:LATENCY_DOC_CHARS])
    return docs


def peak_rss_bytes() -> int:
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return rss if sys.platform == "darwin" else rss * 1024  # Linux reports KiB


def run_single(model: str, threads: int, runs: int, batch_size: int) -> dict:
    """Benchmark one model in this process; returns the metrics."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from raggie_embeddings.config import Settings
    from raggie_embeddings.providers.models import ensure_model, register_custom_rerankers

    cfg = Settings(_env_file=None, reranker_model=model)
    register_custom_rerankers()
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    path = ensure_model(model, cfg.model_cache_dir)
    kwargs = {"model_name": model, "cache_dir": cfg.model_cache_dir, "threads": threads}
    if path:
        kwargs["specific_model_path"] = path
    started = time.perf_counter()
    encoder = TextCrossEncoder(**kwargs)
    load_seconds = time.perf_counter() - started

    queries = load_queries(DATASET)
    limit = cfg.reranker_max_doc_chars
    per_lang: dict[str, list[float]] = {}
    for q in queries:
        scores = list(
            encoder.rerank(q["query"], [d[:limit] for d in q["docs"]], batch_size=batch_size)
        )
        per_lang.setdefault(q["lang"], []).append(ndcg_at_k(scores, q["rels"]))
    all_ndcg = [v for values in per_lang.values() for v in values]

    docs = latency_docs(queries)
    list(encoder.rerank(queries[0]["query"], docs, batch_size=batch_size))  # warm-up
    timings = []
    for i in range(runs):
        q = queries[i % len(queries)]["query"]
        t0 = time.perf_counter()
        list(encoder.rerank(q, docs, batch_size=batch_size))
        timings.append(time.perf_counter() - t0)
    timings.sort()
    p95 = timings[min(len(timings) - 1, math.ceil(0.95 * len(timings)) - 1)]
    return {
        "model": model,
        "queries": len(queries),
        "ndcg10": statistics.fmean(all_ndcg),
        "ndcg10_by_lang": {lang: statistics.fmean(v) for lang, v in sorted(per_lang.items())},
        "p50_seconds": statistics.median(timings),
        "p95_seconds": p95,
        "load_seconds": load_seconds,
        "peak_rss_bytes": peak_rss_bytes(),
        "threads": threads,
        "runs": runs,
        "batch_size": batch_size,
    }


def gate(result: dict, baseline: dict) -> dict[str, bool]:
    return {
        "ndcg": result["ndcg10"] >= baseline["ndcg10"] - NDCG_GATE_DELTA,
        "p95": result["p95_seconds"] <= P95_GATE_SECONDS,
        "rss": result["peak_rss_bytes"] <= RSS_GATE_BYTES,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--models", nargs="*", default=CANDIDATES)
    parser.add_argument("--baseline", default=BASELINE)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument(
        "--batch-size",
        type=int,
        default=8,
        help="pairs per ONNX forward pass (RERANKER_BATCH_SIZE)",
    )
    parser.add_argument("--json", action="store_true", help="print raw JSON results")
    parser.add_argument("--single", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.single:
        print(json.dumps(run_single(args.single, args.threads, args.runs, args.batch_size)))
        return 0

    env = {**os.environ, "OMP_NUM_THREADS": str(args.threads)}
    results = {}
    for model in [args.baseline, *args.models]:
        print(f"benchmarking {model} ...", file=sys.stderr, flush=True)
        # argv list, no shell: model ids come from our own CLI flags, not untrusted input.
        argv = [
            sys.executable,
            __file__,
            "--single",
            model,
            "--threads",
            str(args.threads),
            "--runs",
            str(args.runs),
            "--batch-size",
            str(args.batch_size),
        ]
        # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-tainted-env-args.dangerous-subprocess-use-tainted-env-args  # noqa: E501
        out = subprocess.run(argv, env=env, check=True, capture_output=True, text=True)
        results[model] = json.loads(out.stdout.strip().splitlines()[-1])

    baseline = results[args.baseline]
    if args.json:
        print(json.dumps(results, indent=2))
    header = (
        f"{'model':48} {'nDCG@10':>8} {'TR':>6} {'EN':>6} {'p50 s':>7} {'p95 s':>7} "
        f"{'RSS GB':>7}  gate"
    )
    print(header)
    print("-" * len(header))
    first_candidate_passed = True
    for index, (model, r) in enumerate(results.items()):
        verdict = "baseline"
        if model != args.baseline:
            checks = gate(r, baseline)
            verdict = (
                "PASS"
                if all(checks.values())
                else ("FAIL(" + ",".join(k for k, ok in checks.items() if not ok) + ")")
            )
            if index == 1 and not all(checks.values()):
                first_candidate_passed = False
        langs = r["ndcg10_by_lang"]
        print(
            f"{model:48} {r['ndcg10']:8.4f} {langs.get('tr', 0):6.3f} {langs.get('en', 0):6.3f} "
            f"{r['p50_seconds']:7.3f} {r['p95_seconds']:7.3f} "
            f"{r['peak_rss_bytes'] / 1024**3:7.2f}  {verdict}"
        )
    print(
        f"\ngate: nDCG@10 >= {baseline['ndcg10'] - NDCG_GATE_DELTA:.4f} "
        f"(baseline - {NDCG_GATE_DELTA}), p95 <= {P95_GATE_SECONDS}s "
        f"(24 docs x {LATENCY_DOC_CHARS} chars, threads={args.threads}, "
        f"batch={args.batch_size}), "
        f"RSS <= {RSS_GATE_BYTES / 1024**3:.1f} GB; {baseline['queries']} queries"
    )
    return 0 if first_candidate_passed else 1


if __name__ == "__main__":
    sys.exit(main())
