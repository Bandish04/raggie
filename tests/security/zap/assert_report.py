#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""Fail the nightly DAST job on the findings we gate on.

Reads ZAP JSON reports (`-J`) and .zap/rules.tsv, and fails when a report has
  - any High alert (riskcode 3), unless the rule is IGNOREd, or
  - any alert whose rule is marked FAIL (the curated Medium set: CSP, cookie
    flags, CORS / cross-domain misconfiguration, ...), at any risk level.
Alerts ZAP itself marks as false positives (confidence 0) never fail. A missing
or unreadable report fails too, so a crashed scan cannot pass silently.

--auth-summary (written by auth_hook.py, once per authenticated scan) also fails
the job when the scan never sent its bearer, or no authenticated request got a
2xx: the scan then ran unauthenticated and proves nothing about the API.

rules.tsv: `<plugin id>\t<IGNORE|WARN|FAIL>\t<justification>`, `#` comments.
The same file is passed to the ZAP scripts (`-c`), which read the first two
columns; the justification is mandatory here so every exception is explained.

Usage: assert_report.py --rules .zap/rules.tsv [--auth-summary auth.json ...]
                        report.json [report.json ...]
Exit codes: 0 pass, 1 gated findings, 2 missing/invalid input.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ACTIONS = {"IGNORE", "WARN", "FAIL"}
RISK = {"0": "Informational", "1": "Low", "2": "Medium", "3": "High"}


def load_rules(path: Path) -> dict[str, str]:
    rules: dict[str, str] = {}
    for n, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        cols = line.rstrip("\n").split("\t")
        if len(cols) > 3:
            raise ValueError(f"{path}:{n}: expected three tab-separated columns (ZAP's format)")
        rule_id, action = cols[0].strip(), cols[1].strip() if len(cols) > 1 else ""
        if action not in ACTIONS:
            raise ValueError(f"{path}:{n}: rule {rule_id}: action must be one of {sorted(ACTIONS)}")
        if len(cols) < 3 or not cols[2].strip():
            raise ValueError(f"{path}:{n}: rule {rule_id}: a justification column is required")
        rules[rule_id] = action
    return rules


def evaluate(reports: list[dict], rules: dict[str, str]) -> list[str]:
    violations: list[str] = []
    for report in reports:
        for site in report.get("site", []):
            for alert in site.get("alerts", []):
                rule_id = str(alert.get("pluginid", ""))
                action = rules.get(rule_id, "WARN")
                if action == "IGNORE" or str(alert.get("confidence")) == "0":
                    continue
                risk = str(alert.get("riskcode", "0"))
                if action == "FAIL" or risk == "3":
                    uris = sorted({i.get("uri", "") for i in alert.get("instances", [])})[:3]
                    where = f"{alert.get('count', len(uris))}x on {site.get('@name', '?')}"
                    violations.append(
                        f"[{RISK.get(risk, risk)}] {rule_id} {alert.get('alert', '')}"
                        f" ({where}, e.g. {', '.join(uris)})"
                    )
    return violations


def auth_problems(name: str, summary: dict) -> list[str]:
    statuses = summary.get("auth_status", {})
    if not summary.get("with_auth"):
        return [f"{name}: scan ran unauthenticated (no request carried Authorization)"]
    if not any(code.startswith("2") for code in statuses):
        return [
            f"{name}: scan ran unauthenticated (every request with Authorization was "
            f"rejected: {statuses})"
        ]
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rules", required=True, type=Path)
    parser.add_argument("--auth-summary", action="append", default=[], type=Path)
    parser.add_argument("reports", nargs="+", type=Path)
    args = parser.parse_args(argv)

    try:
        rules = load_rules(args.rules)
        reports = [json.loads(p.read_text()) for p in args.reports]
        summaries = {p.stem: json.loads(p.read_text()) for p in args.auth_summary}
    except (OSError, ValueError) as exc:  # JSONDecodeError is a ValueError
        print(f"assert_report: {exc}", file=sys.stderr)
        return 2

    violations = evaluate(reports, rules)
    for name, summary in summaries.items():
        violations += auth_problems(name, summary)
    for v in violations:
        print(f"::error::ZAP {v}")
    print(f"assert_report: {len(reports)} report(s), {len(violations)} gated finding(s)")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
