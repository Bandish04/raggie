# Benchmarks

Every performance or quality claim Raggie makes must point at a result file in
this directory. A result is produced by one command from [`bench/`](../../bench),
is dated, and records the hardware, the source revision, the stack settings and
the raw numbers (CSV + JSON next to the markdown). A number that has not been
measured this way is not published — in particular, the 50,000-stream A5 target
stays a target until an `a5-sse` result shows it.

## Harnesses

| Harness | Gate | What it measures | Command |
|---|---|---|---|
| `a2-retrieval` | A2: retrieval p95 < 200 ms | Time to the edge's `sources` event for real chat turns (embed → Qdrant hybrid → rerank happen before it), cache-cold and cache-warm passes, p50/p95/p99 | `cd bench && go run ./a2-retrieval` |
| `a3-ingest` | A3: 50-page PDF ≤ 10 s | Upload → SUCCESS for a generated, text-heavy TR+EN 50-page PDF, split into upload / queue / worker processing, plus the server-side span | `cd bench && go run ./a3-ingest` |
| `a5-sse` | A5: concurrent SSE streams | Escalating stages of N concurrent chat streams (mock LLM): success rate, time-to-first-token, throughput, edge memory/CPU; reports the maximum sustainable N | `cd bench && go run ./a5-sse -stages 10,50,100,200,400` |
| `eval` | RAG quality | recall@k, hit@k, MRR@10 and citation-hit rate over the golden set's expected documents; with a real LLM exact/contains answer match and correct abstention; all by language and question type | `cd bench && go run ./eval` |
| `judge-eval` | Judge accuracy | The eval worker's own faithfulness judge over the labeled set in [`examples/judge-eval`](../../examples/judge-eval) (80 items, TR+EN). Reports precision, recall and F1 for flagging unfaithful answers at `EVAL_FAITHFULNESS_THRESHOLD`, ROC-AUC, a threshold sweep, breakdowns by language and error type, and items not scored (timeouts, errors) | `make eval-judge` (Python; `ARGS=--dry-run` only validates the dataset) |

Each command writes `docs/benchmarks/<name>-<YYYY-MM-DD>.md` (plus `.csv` and
`.json`; a second run the same day gets a `-2` suffix — nothing is ever
overwritten). `-dry-run` runs the same code against an in-process fake stack and
writes to a temp directory: use it to check the harness, never quote it.
`go run ./<name> -h` lists every flag.

`judge-eval` is the one Python harness (`bench/judge_eval.py`), because it imports
the judge from `services/workers`. It runs against whatever OpenAI-compatible
endpoint the eval worker would use (`LLMAAS_BASE_URL`, `LLMAAS_API_KEY`,
`LLMAAS_CHAT_MODEL`, plus `EVAL_*`), needs no stack, and writes
`judge-eval-<date>.md` and `.json`. Set `JUDGE_EVAL_HARDWARE` to record where the
model runs. Results describe that model only: rerun it for every judge model you
deploy. A mock LLM's scores say nothing about quality, so don't benchmark one.

## Running against a stack

The harnesses target the throwaway e2e stack (mock LLM, its own ports and
volumes, never your `.env`):

```bash
eval "$(scripts/e2e-stack.sh up)"     # builds and starts; exports E2E_* URLs + setup token
cd bench && go run ./a3-ingest
scripts/e2e-stack.sh down             # when done (deletes the volumes)
```

**Identity.** On a fresh stack the harness bootstraps the first admin with the
setup token (`E2E_SETUP_TOKEN`) and remembers the generated credentials in
`$RAGGIE_BENCH_DIR` (default: the user cache dir, `raggie-bench/admin.json`,
mode 0600). On an onboarded stack it logs in with `RAGGIE_BENCH_EMAIL` /
`RAGGIE_BENCH_PASSWORD`, else the remembered credentials, else the web e2e
suite's saved state (`web/e2e/stack/.state/stack.json`). The web e2e onboarding
spec expects a fresh stack, so run the web suite first or give the benchmarks
their own stack. Every harness creates its own workspace (`-workspace <id>`
reuses an indexed one, e.g. to skip re-indexing the corpus between eval runs).

**Stack settings for load tests.** The e2e stack keeps production defaults,
which deliberately throttle a single user:

| Setting | Default | Needed for |
|---|---|---|
| `RATE_LIMIT_ENABLED` | `true` (30 chats/min/user) | `a2-retrieval` (> 30 turns/min), `a5-sse`, `eval` — set `false`, or pace with `-pace 2s` |
| `LLMAAS_CHAT_MAX_CONCURRENCY` | `64` | `a5-sse` — the edge sheds (503 `busy`) above it; raise it to find the edge's own ceiling |
| `MOCKLLM_TOKEN_DELAY_MS` | `15` | `a5-sse` — per-token pace of the mock LLM, i.e. how long each stream stays open |

`scripts/e2e-stack.sh` applies overrides last, so they win over its defaults
and reach both the app services and compose interpolation. Either list them in
a file of `KEY=VALUE` lines (`#` comments allowed) or set one
`E2E_ENV_<KEY>=value` variable per setting; the variables are applied after the
file. Re-running `up` with new values recreates the affected services:

```bash
printf 'RATE_LIMIT_ENABLED=false\nLLMAAS_CHAT_MAX_CONCURRENCY=1024\n' > bench.env
E2E_EXTRA_ENV_FILE=bench.env scripts/e2e-stack.sh up
# or, per setting:
E2E_ENV_RATE_LIMIT_ENABLED=false E2E_ENV_MOCKLLM_TOKEN_DELAY_MS=15 scripts/e2e-stack.sh up
```

The report records these settings automatically: the harness reads a fixed
whitelist of non-secret keys (embedding provider/model, reranker, retrieval and
concurrency knobs, rate limiting) from `-stack-env` (default: the e2e stack's
`app.env`). Secrets, URLs and hostnames are never read into a report.

| Variable | Purpose |
|---|---|
| `RAGGIE_BENCH_CONTROL_PLANE_URL` / `E2E_CONTROL_PLANE_URL` | control plane (default `http://127.0.0.1:58000`) |
| `RAGGIE_BENCH_EDGE_URL` / `E2E_EDGE_URL` | edge (default `http://localhost:8090`) |
| `RAGGIE_BENCH_SETUP_TOKEN` / `E2E_SETUP_TOKEN` | bootstrap a fresh stack |
| `RAGGIE_BENCH_EMAIL`, `RAGGIE_BENCH_PASSWORD` | super admin of an onboarded stack |
| `RAGGIE_BENCH_DIR` | where generated admin credentials are kept |
| `RAGGIE_BENCH_METRICS_TOKEN` | bearer for `a5-sse -metrics-url` |
| `RAGGIE_E2E_DIR` | e2e stack state dir (locates `app.env`) |

## Methodology and caveats

**A2 — retrieval.** The edge has no retrieval-only endpoint. It embeds the
query (`/v1/query` on the embeddings gateway), runs the Qdrant hybrid search
and reranks *before* it writes the SSE headers, so the time to the `sources`
event bounds retrieval from above; it also includes persisting the user turn
and opening the mock LLM stream, and excludes generation. A warm-up is
discarded, then two passes run: **cache-cold** (every query made unique, so the
gateway's query-embedding cache cannot hit) and **cache-warm** (a primed set
repeated). In cloud embedding mode the gap between the two is the cache's
effect; in local mode both mostly measure the local model. The seeded workspace
holds the first 30 documents of the golden set's corpus by default (`-seed-docs`), and the queries are the golden questions.

**A3 — ingestion.** `a3-ingest -generate-only a3.pdf` writes the exact file
(same `-pages`/`-seed` → byte-identical, SHA-256 in the report). Its text is
extracted losslessly by pdfplumber (the worker's parser) and poppler. Queue
wait and worker processing are observed by polling (`-poll`, default 250 ms),
so each carries up to one poll interval of error; the server-side
`created_at → updated_at` span is exact but includes the queue. A3 counts from
worker pickup, so compare the *processing* row with the 10 s target. The worker
exposes no per-stage timing, so a parse / chunk / embed / upsert split needs
worker instrumentation first.

**A5 — concurrent streams.** Each stream loops complete chat turns
(retrieval, persistence, token stream, `done`, `chat.completed`) — a far
heavier load than idle connections. A stage passes when ≥ 99 % of its turns
complete and the TTFT p95 is ≤ 2 s (both flags); the result is the last stage
of an unbroken passing run, and the harness stops at the first failure unless
`-continue`. Edge memory/CPU come from `docker stats` of the edge container
(`-docker-stats-interval`, 0 disables it on an overloaded engine). Edge gauges
need `-metrics-url`: the edge's metrics listener is internal and its image is
distroless; it exports no Go runtime gauges (goroutines), so those are reported
only if an endpoint provides them. The client raises its open-file limit and
reports it. On a laptop the load generator shares the CPUs with the stack, so
the result is a lower bound for a dedicated server.

**Eval — RAG quality.** The golden set is
[`examples/golden/golden.yaml`](../../examples/golden/golden.yaml): each item
has an `id`, the `question`, its `language` (tr|en), the exact `answer`
(`null` when the corpus does not answer it) with optional `answer_variants`,
the `expected_documents` that hold the answer, verbatim `evidence`
(`{document, quote}` entries; plain quote strings are accepted too), a `type`
(`single-fact`, `table-lookup`, `multi-hop`, `temporal/version`,
`negative/unanswerable`, `ocr`) and a `difficulty`. The file is a mapping
with `version: 1`, `corpus:` (the corpus directory, relative to the file),
`questions:` and an optional `exclude:`; `-golden` / `-corpus` override the
file and the corpus. A corpus `README.md` is never uploaded. The
harness validates the set against the corpus before it uploads anything.

- **Retrieval** (answerable items only): chunks are collapsed to their
  document, best rank kept, and compared with `expected_documents` under the
  spec's rule. A `multi-hop` question needs **all** of them: hit@k only when
  every one is in the top k, recall@k gives partial credit, and MRR uses the
  rank that completes the set. Every other type is answered by **any** one of
  them, so recall@k = hit@k. Citation hit = the answer's `[n]` markers resolve
  to an expected document. A failed turn counts as retrieving nothing.
- **Answers** (`-llm real` only): answers are normalized (Unicode NFC,
  Turkish-aware case, punctuation, citation markers, `1.250` = `1,250` =
  `1250`, decimal comma → dot). *Exact* = the whole answer equals the answer
  or a variant; *contains* = one of them occurs on token boundaries, and a
  compound answer (`"Ece Polat; 30 Jun 2026"`) needs every part. *Correct abstention* =
  unanswerable items the model declined; *false abstention* = answerable ones
  it declined. Abstention is a Turkish + English phrase-list heuristic —
  spot-check the per-question CSV, which includes every answer.
- Every metric is reported overall, per language and per type.
- With the mock LLM, answers are templated from the retrieved sources (they
  cite `[1]`/`[2]`), so the citation-hit rate equals top-1/2 retrieval accuracy
  and the answer metrics are not reported. `-answer-metrics` additionally reads
  the eval worker's faithfulness and citation scores from the stack's postgres
  (`docker exec … psql`).
- `-dry-run` uses the five-item fixture in `bench/eval/testdata/`.

**Comparison matrix.** Embedding provider (local e5 vs cloud presets) and the
reranker are stack settings, not harness flags. Run `a2-retrieval` and `eval`
once per configuration; the reports record the configuration, so the results
compare side by side.

## Layout

- `templates/` — the report layouts (Go `text/template`, rendered by the
  harnesses at run time; edit here to change every future report).
- `<name>-<date>.md|.csv|.json` — results.

## Results

No measured results have been published yet.
