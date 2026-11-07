# SPDX-License-Identifier: Apache-2.0

"""bench/judge_eval.py: the labeled faithfulness set and the metrics the judge
benchmark reports. No model, no network: a fake judge returns known scores."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]


def _load_harness():
    spec = importlib.util.spec_from_file_location("judge_eval", REPO / "bench" / "judge_eval.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["judge_eval"] = module
    spec.loader.exec_module(module)
    return module


je = _load_harness()

DOC_EN = "Load_Test_Report.docx"
DOC_TR = "Teknik_Mimari.pdf"
PASSAGE_EN = "At 3,000 RPS sustained for 60 minutes the API recorded a p95 latency of 212 ms."
PASSAGE_TR = "NebulaCRM, Kubernetes 1.30 üzerinde koşan 34 mikroservisten oluşur."
CORPUS = {
    DOC_EN: je.CorpusDoc(lang="en", text=je.normalize(f"Intro. {PASSAGE_EN} More text.")),
    DOC_TR: je.CorpusDoc(lang="tr", text=je.normalize(f"Giriş.\n{PASSAGE_TR}")),
}


def _item(**overrides) -> dict:
    item = {
        "id": "en-001",
        "language": "en",
        "label": "faithful",
        "context": [{"document": DOC_EN, "passage": PASSAGE_EN}],
        "answer": "p95 was 212 ms at 3,000 RPS.",
    }
    item.update(overrides)
    return item


def _errors(*items) -> list[str]:
    return je.validate_dataset({"version": 1, "items": list(items)}, CORPUS)


def test_valid_items_pass() -> None:
    unfaithful = _item(
        id="tr-001",
        language="tr",
        label="unfaithful",
        error_type="wrong_number",
        answer="36 mikroservis.",
        context=[{"document": DOC_TR, "passage": PASSAGE_TR}],
    )
    assert _errors(_item(), unfaithful) == []


def test_passage_must_appear_verbatim_in_its_document() -> None:
    # Whitespace and Unicode form are normalized; wording is not.
    reflowed = PASSAGE_EN.replace(" a p95", "\n a  p95")
    assert _errors(_item(context=[{"document": DOC_EN, "passage": reflowed}])) == []
    errors = _errors(_item(context=[{"document": DOC_EN, "passage": "p95 of 213 ms"}]))
    assert len(errors) == 1 and "not found verbatim" in errors[0]


@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        ({"context": [{"document": "Missing.pdf", "passage": PASSAGE_EN}]}, "unknown document"),
        ({"label": "faithful", "error_type": "wrong_number"}, "faithful items take no error_type"),
        ({"label": "unfaithful"}, "error_type"),
        ({"label": "unfaithful", "error_type": "typo"}, "error_type"),
        ({"label": "maybe"}, "label"),
        ({"language": "de"}, "language"),
        ({"language": "tr"}, "is en, item is tr"),
        ({"context": []}, "1-3 passages"),
        ({"context": [{"document": DOC_EN, "passage": PASSAGE_EN}] * 4}, "1-3 passages"),
        ({"answer": "  "}, "answer"),
        ({"tags": ["vibes"]}, "unknown tag"),
    ],
)
def test_schema_errors(overrides, fragment) -> None:
    errors = _errors(_item(**overrides))
    assert errors and any(fragment in e for e in errors), errors


def test_duplicate_ids_are_rejected() -> None:
    assert any("duplicate id" in e for e in _errors(_item(), _item()))


def _result(
    label: str, score: float | None, *, lang: str = "en", error_type: str | None = None
) -> je.Result:
    return je.Result(
        id=f"{label}-{score}",
        language=lang,
        label=label,
        error_type=error_type,
        score=score,
        status="scored" if score is not None else "unscored",
    )


FIXTURE = [
    _result("unfaithful", 0.1, error_type="wrong_number"),
    _result("unfaithful", 0.4, lang="tr", error_type="partial"),
    _result("unfaithful", 0.8, lang="tr", error_type="partial"),
    _result("faithful", 0.9),
    _result("faithful", 0.6, lang="tr"),
    _result("faithful", 1.0),
    _result("faithful", None),  # timed out: counted, never scored
]


def test_metrics_at_threshold() -> None:
    m = je.metrics_at(FIXTURE, 0.7)
    assert (m.tp, m.fp, m.fn, m.tn) == (2, 1, 1, 2)
    assert m.precision == pytest.approx(2 / 3)
    assert m.recall == pytest.approx(2 / 3)
    assert m.f1 == pytest.approx(2 / 3)
    assert m.accuracy == pytest.approx(4 / 6)


def test_score_equal_to_threshold_is_not_flagged() -> None:
    # Same rule as the eval worker: flagged iff score < threshold.
    m = je.metrics_at([_result("faithful", 0.7)], 0.7)
    assert (m.fp, m.tn) == (0, 1)


def test_roc_auc() -> None:
    assert je.roc_auc(FIXTURE) == pytest.approx(8 / 9)
    assert je.roc_auc([_result("unfaithful", 0.5), _result("faithful", 0.5)]) == 0.5
    assert je.roc_auc([_result("faithful", 0.5)]) is None  # one class only


def test_sweep_and_best_threshold() -> None:
    rows = je.sweep(FIXTURE, [0.5, 0.7, 0.85])
    assert [r.threshold for r in rows] == [0.5, 0.7, 0.85]
    assert rows[2].recall == 1.0 and rows[2].fp == 1  # 0.8 now flagged, 0.6 still
    assert je.best_f1(rows).threshold == 0.85


def test_breakdowns() -> None:
    by_lang = je.breakdown(FIXTURE, 0.7, "language")
    assert (by_lang["tr"].tp, by_lang["tr"].fn, by_lang["tr"].fp) == (1, 1, 1)
    detection = je.detection_by_error_type(FIXTURE, 0.7)
    assert detection == {"partial": (1, 2), "wrong_number": (1, 1)}


def test_not_scored_is_counted_separately() -> None:
    assert je.not_scored(FIXTURE) == {"unscored": 1}


def test_runner_passes_the_production_context_and_survives_failures() -> None:
    seen: list[tuple[str, str]] = []

    class FakeJudge:
        async def score(self, answer: str, context: str) -> float | None:
            seen.append((answer, context))
            if answer == "boom":
                raise RuntimeError("upstream 500")
            return None if answer == "slow" else 0.25

    two = [{"document": DOC_EN, "passage": "first"}, {"document": DOC_EN, "passage": "second"}]
    items = [_item(id="a", context=two), _item(id="b", answer="boom"), _item(id="c", answer="slow")]
    results = asyncio.run(je.run_judge(items, FakeJudge(), concurrency=2))
    assert [(r.id, r.status, r.score) for r in results] == [
        ("a", "scored", 0.25),
        ("b", "error", None),
        ("c", "unscored", None),
    ]
    # Same flattening as the eval worker (store.context_from_sources).
    assert ("p95 was 212 ms at 3,000 RPS.", "first\n\nsecond") in seen


def test_report_mentions_model_threshold_and_counts() -> None:
    report = je.render_report(
        FIXTURE,
        threshold=0.7,
        meta={
            "model": "test-model",
            "endpoint": "llm.example",
            "date": "2026-11-04",
            "hardware": "test rig",
            "client": "darwin arm64",
            "revision": "abc123",
            "dataset": "examples/judge-eval/judge_eval.yaml",
        },
    )
    for needle in (
        "test-model",
        "0.7",
        "ROC-AUC",
        "0.889",
        "test rig",
        "| tr |",
        "partial",
        "Not scored: 1",
    ):
        assert needle in report, needle


def test_the_shipped_dataset_is_valid_and_balanced() -> None:
    data = je.load_dataset(je.DATASET)
    assert je.validate_dataset(data, je.corpus_index()) == []
    items = data["items"]
    langs = {lang: sum(i["language"] == lang for i in items) for lang in ("tr", "en")}
    unfaithful = [i for i in items if i["label"] == "unfaithful"]
    assert 75 <= len(items) <= 90
    assert min(langs.values()) >= 0.4 * len(items)
    assert 0.5 <= len(unfaithful) / len(items) <= 0.6
    assert {i["error_type"] for i in unfaithful} == set(je.ERROR_TYPES)


# Real organisations that the synthetic corpus once named by accident. Every
# company in examples/ must be invented (examples/sample-corpus/README.md).
REAL_ORGANISATIONS = ("Denge Bağımsız Denetim",)


def test_synthetic_data_names_no_known_real_organisation() -> None:
    sources = [
        *(REPO / "scripts" / "corpus").rglob("*.py"),
        REPO / "scripts" / "corpus" / "WORLD.md",
        REPO / "examples" / "golden" / "golden.yaml",
        je.DATASET,
        *(
            p
            for p in (REPO / "examples" / "sample-corpus").rglob("*")
            if p.suffix in {".md", ".txt"}
        ),
    ]
    hits = [
        (p.relative_to(REPO), name)
        for p in sources
        for name in REAL_ORGANISATIONS
        if name in p.read_text(encoding="utf-8")
    ]
    assert hits == []
