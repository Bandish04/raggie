# Golden set

`golden.yaml` is an exact-answer question set over the synthetic
[sample corpus](../sample-corpus/README.md). Each question names the documents
that answer it, the short answer, and verbatim evidence quotes. It is the input
for retrieval and answer-quality benchmarks (`bench/eval`) and is dedicated to
the public domain under CC0 1.0, like the corpus.

## At a glance

181 questions — 124 Turkish, 57 English (English questions often target Turkish
documents, so they test cross-lingual retrieval). Every one of the 39 corpus
documents is the target of at least one question.

| Type | Count | What it tests |
|---|---|---|
| `single-fact` | 64 | One fact stated in prose |
| `table-lookup` | 41 | A cell or row in a PDF/DOCX/XLSX/PPTX table |
| `temporal/version` | 30 | Picking the right version/period among near-miss distractors (2025 vs 2026 policy, Q2 vs Q3, v3.3 vs v3.4) |
| `multi-hop` | 26 | Chaining facts from two (or three) documents, usually across departments |
| `negative/unanswerable` | 15 | The corpus does not contain the answer; the system should say so |
| `ocr` | 5 | Facts that exist only in the scanned PNG memo |

Difficulty: 67 easy, 84 medium, 30 hard.

## Schema

```yaml
version: 1
corpus: "../sample-corpus"         # corpus directory, relative to this file
questions:
  - id: "x-003"                     # unique; prefix = department (arge-, bt-, ceo-, fin-,
                                    #   huk-, ik-, kal-, md-, ps-, urun-) or x- for cross-department
    department: "cross"             # corpus folder the question belongs to, or "cross"
    language: en                    # tr | en — language of the question
    type: "multi-hop"               # see the table above
    difficulty: hard                # easy | medium | hard
    question: "Given April 2026's uptime after the database outage, ..."
    answer: "%10"                   # short exact answer; null when unanswerable
    answer_variants: ["10%"]        # optional equivalent spellings
    expected_documents: [Postmortem_INC-2026-0417_Database_Outage.pdf, Destek_SLA_Matrisi_2026.xlsx]
    evidence:                       # verbatim quotes, one or more per expected document
      - document: Postmortem_INC-2026-0417_Database_Outage.pdf
        quote: "Monthly uptime for April 2026 was 99.61% for the shared production cluster."
      - document: Destek_SLA_Matrisi_2026.xlsx
        quote: "Kurumsal | %99,9 altı – %99,0 ve üzeri | %10 | Kurumsal taahhüt: %99,9"
    absent_terms: [...]             # negative questions only (optional): strings that occur nowhere in the corpus
    notes: "..."                    # optional explanation (why unanswerable, the reasoning chain)
```

Field semantics:

- `expected_documents` are file basenames (unique across the corpus). For
  `multi-hop` questions **all** listed documents are needed to answer. For every
  other type each listed document answers the question on its own (some facts
  are deliberately repeated, e.g. the API v2 sunset date appears in the API
  reference, both release notes and the strategy deck), so retrieving **any**
  of them is a hit. Negative questions have an empty list.
- `answer` is the shortest string that is correct. A compound answer joins its
  parts with `"; "` (e.g. `"Ece Polat; 30 Jun 2026"`); a correct response states
  every part. Values read from XLSX cells are given as the worker extracts them
  (`"2750"`, `"168.4"`), with formatted spellings in `answer_variants`
  (`"2.750 TL"`). Turkish number formatting (`1.290`, `%15`, `99,9`) is kept as
  written in the source.
- `evidence.quote` is a verbatim substring of the text Raggie's ingestion
  worker extracts from that document. For table rows the quote uses the
  extractor's ` | ` cell separator (DOCX/XLSX/PPTX) or plain spacing (PDF).

## Scoring guidance

- Retrieval (`hit@k`, `recall@k`, MRR): compare retrieved document names with
  `expected_documents` using the any/all rule above. Skip negative questions,
  or score them separately.
- Answer correctness: normalise case, Unicode (NFC) and whitespace, then accept
  a response that contains `answer` or any `answer_variants` entry (all parts for
  compound answers). An LLM judge can use `evidence` as the reference.
- Unanswerable questions: a correct response declines or says the sources do
  not contain the answer; any concrete value is a hallucination. Several are
  traps — e.g. `x-n06` asks for the approved 2027 budget, which does not exist
  yet, while the 2026 budget does.
- Faithfulness: `evidence` quotes are the minimal supporting passages, useful as
  gold context for groundedness metrics.

## Validation

```bash
uv run scripts/corpus/validate.py
```

The validator extracts every corpus file with the ingestion worker's own parser
(`services/workers/raggie_workers/ingestion/parsing.py`; the PNG is OCR'd with
a local Tesseract `tur+eng` when installed — otherwise its quotes are checked
against the generator's source text and the run prints that OCR was not verified) and checks that ids are unique, every expected document
exists, every quote appears in its document, every answer appears in the
evidence, `absent_terms` occur nowhere, and every document is covered. Matching
normalises Unicode, whitespace and table separators. Run it after editing the
corpus content (`scripts/corpus/content/`) or this file; it must report `OK`.
