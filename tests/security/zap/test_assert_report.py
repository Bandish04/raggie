# SPDX-License-Identifier: Apache-2.0

"""Gate logic for the nightly ZAP scans (assert_report.py)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from assert_report import evaluate, load_rules, main


def _report(*alerts: dict) -> dict:
    return {"site": [{"@name": "http://localhost:3310", "alerts": list(alerts)}]}


def _alert(pluginid: str, riskcode: str, confidence: str = "2", name: str = "x") -> dict:
    return {
        "pluginid": pluginid,
        "alert": name,
        "riskcode": riskcode,
        "confidence": confidence,
        "count": "1",
        "instances": [{"uri": "http://localhost:3310/", "method": "GET"}],
    }


@pytest.fixture
def rules(tmp_path: Path) -> dict[str, str]:
    path = tmp_path / "rules.tsv"
    path.write_text(
        "# id\taction\tjustification\n"
        "10038\tFAIL\tCSP header must be set on every HTML response\n"
        "10202\tWARN\tbearer/SameSite+Origin CSRF defence, no form tokens\n"
        "10027\tIGNORE\tcomments in minified framework bundles\n"
        "\n"
    )
    return load_rules(path)


def test_load_rules_reads_id_and_action_and_skips_comments(rules) -> None:
    assert rules == {"10038": "FAIL", "10202": "WARN", "10027": "IGNORE"}


def test_load_rules_rejects_unknown_action(tmp_path: Path) -> None:
    path = tmp_path / "rules.tsv"
    path.write_text("10038\tBLOCK\tnope\n")
    with pytest.raises(ValueError, match="10038"):
        load_rules(path)


def test_load_rules_requires_a_justification(tmp_path: Path) -> None:
    path = tmp_path / "rules.tsv"
    path.write_text("10027\tIGNORE\n")
    with pytest.raises(ValueError, match="justification"):
        load_rules(path)


def test_clean_report_passes(rules) -> None:
    assert evaluate([_report(_alert("10202", "2"), _alert("10096", "1"))], rules) == []


def test_any_high_fails_unless_ignored(rules) -> None:
    violations = evaluate([_report(_alert("40018", "3", name="SQL Injection"))], rules)
    assert len(violations) == 1 and "40018" in violations[0] and "High" in violations[0]


def test_high_marked_false_positive_by_zap_is_skipped(rules) -> None:
    assert evaluate([_report(_alert("40018", "3", confidence="0"))], rules) == []


def test_ignored_rule_never_fails(rules) -> None:
    assert evaluate([_report(_alert("10027", "3"))], rules) == []


def test_curated_fail_rule_fails_at_any_risk(rules) -> None:
    violations = evaluate([_report(_alert("10038", "2", name="CSP Header Not Set"))], rules)
    assert len(violations) == 1 and "10038" in violations[0]


def test_unlisted_medium_only_warns(rules) -> None:
    assert evaluate([_report(_alert("90022", "2"))], rules) == []


def test_main_exit_codes(tmp_path: Path) -> None:
    rules_path = tmp_path / "rules.tsv"
    rules_path.write_text("10038\tFAIL\tCSP must be set\n")
    ok = tmp_path / "ok.json"
    ok.write_text(json.dumps(_report(_alert("10096", "1"))))
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(_report(_alert("10038", "2"))))

    assert main(["--rules", str(rules_path), str(ok)]) == 0
    assert main(["--rules", str(rules_path), str(ok), str(bad)]) == 1


def test_main_fails_when_a_report_is_missing(tmp_path: Path) -> None:
    rules_path = tmp_path / "rules.tsv"
    rules_path.write_text("10038\tFAIL\tCSP must be set\n")
    # A scan that crashed before writing its report must not pass silently.
    assert main(["--rules", str(rules_path), str(tmp_path / "missing.json")]) == 2


def test_load_rules_rejects_extra_columns_zap_cannot_parse(tmp_path: Path) -> None:
    # ZAP's loader unpacks exactly three tab-separated fields per line.
    path = tmp_path / "rules.tsv"
    path.write_text("10038\tFAIL\tCSP must be set\textra\n")
    with pytest.raises(ValueError, match="three"):
        load_rules(path)
