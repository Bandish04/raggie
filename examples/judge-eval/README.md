# Faithfulness-judge eval set

`judge_eval.yaml` is a labeled set for measuring the eval worker's LLM judge
(`services/workers/raggie_workers/evaluation/judge.py`): given a context and an
answer, does the judge score unfaithful answers below the threshold and faithful
ones above it? Run it with `make eval-judge` (see
[docs/benchmarks/README.md](../../docs/benchmarks/README.md)).

Like the corpus it quotes, the set is released into the public domain under
[CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/).

## Composition

80 items, 40 Turkish and 40 English: 36 faithful and 44 unfaithful.

| Error type | What is wrong | tr | en |
|---|---|---|---|
| `wrong_number` | one number, date or time differs from the context | 5 | 5 |
| `wrong_entity` | a person, place, plan, cause or office is swapped | 5 | 5 |
| `unsupported_claim` | adds a claim the context does not make | 4 | 4 |
| `contradiction` | states the opposite of the context | 4 | 4 |
| `partial` | everything correct except one fabricated detail | 4 | 4 |

The hard cases carry tags:

- `paraphrase`: a faithful answer in different words;
- `unit_format`: a faithful answer that changes the unit or format, for example
  167 minutes → 2 hours 47 minutes, 72 saat → üç gün, 2.400 → 2400, TRY 612.5M →
  612.5 million;
- `multi_passage`: the context has 2–3 passages, sometimes needed together;
- `distractor`: a related passage that does not support the answer (for example
  an approval rule that applies to hotels, not to client entertainment).

## Schema

```yaml
- id: "en-001"                 # unique
  language: en                 # tr | en; every passage comes from a document in this language
  label: faithful              # faithful | unfaithful
  error_type: wrong_number     # unfaithful only (table above)
  tags: [unit_format]          # optional
  context:                     # 1–3 passages, quoted verbatim
    - document: "Load_Test_Report_2026_Q2.docx"   # file name in examples/sample-corpus
      passage: "…"
  answer: "…"
  note: "…"                    # unfaithful only: what is wrong, for reviewers
```

## Labeling rules

- Every context passage is a whole paragraph (or slide note) quoted from the
  corpus. `make eval-judge ARGS=--dry-run` checks that each one appears verbatim,
  ignoring only whitespace and Unicode normalization, in the generator text of
  its document (`scripts/corpus/content`). That text is what `build.py` renders.
  The passages were also checked against the text the ingestion worker extracts
  (`uv run scripts/corpus/validate.py --dump DIR`). Passages that cross a PDF
  page break are avoided, because the extracted text carries the page footer in
  the middle of them.
- A faithful answer is fully supported by its context: every number, name and
  claim can be pointed at, with only unit or format conversions and paraphrase.
- An unfaithful answer differs from its context by exactly the error its type
  names, and otherwise stays close to the context, so the judge can't reject it
  just for being off-topic.
- The judge sees the passages joined the way the eval worker joins a real
  answer's cited chunks (`context_from_sources`, a blank line between passages).

When you change an answer, keep the label honest. If an answer becomes
ambiguous, rewrite it rather than relabel it.
