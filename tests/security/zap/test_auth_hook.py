# SPDX-License-Identifier: Apache-2.0
"""Authenticated-scan evidence: the ZAP hook's summary and the gate on it."""

from __future__ import annotations

import json
from pathlib import Path

from assert_report import auth_problems, main
from auth_hook import summarize


def _msg(status: int, bearer: bool) -> dict:
    auth = "Authorization: Bearer abc.def\r\n" if bearer else ""
    return {
        "requestHeader": f"GET http://127.0.0.1:58000/api/v1/auth/me HTTP/1.1\r\n{auth}Host: x\r\n",
        "responseHeader": f"HTTP/1.1 {status} X\r\nContent-Type: application/json\r\n",
    }


def test_summarize_counts_authenticated_requests_by_status() -> None:
    summary = summarize([_msg(200, True), _msg(401, True), _msg(200, False), _msg(404, True)])
    assert summary == {"total": 4, "with_auth": 3, "auth_status": {"200": 1, "401": 1, "404": 1}}


def test_summarize_matches_the_header_name_case_insensitively() -> None:
    msg = _msg(200, False)
    msg["requestHeader"] = msg["requestHeader"].replace("Host:", "authorization: Bearer t\r\nHost:")
    assert summarize([msg])["with_auth"] == 1


def test_auth_ok_when_some_authenticated_request_succeeded() -> None:
    assert (
        auth_problems("cp", {"total": 9, "with_auth": 5, "auth_status": {"200": 2, "401": 3}}) == []
    )


def test_auth_fails_when_no_request_carried_the_bearer() -> None:
    problems = auth_problems("cp", {"total": 9, "with_auth": 0, "auth_status": {}})
    assert problems and "scan ran unauthenticated" in problems[0]


def test_auth_fails_when_every_authenticated_request_was_rejected() -> None:
    problems = auth_problems("cp", {"total": 9, "with_auth": 4, "auth_status": {"401": 4}})
    assert problems and "scan ran unauthenticated" in problems[0]


def test_main_gates_on_auth_summaries(tmp_path: Path) -> None:
    rules = tmp_path / "rules.tsv"
    rules.write_text("10038\tFAIL\tCSP must be set\n")
    report = tmp_path / "r.json"
    report.write_text(json.dumps({"site": []}))
    good = tmp_path / "auth-ok.json"
    good.write_text(json.dumps({"total": 3, "with_auth": 3, "auth_status": {"200": 3}}))
    bad = tmp_path / "auth-bad.json"
    bad.write_text(json.dumps({"total": 3, "with_auth": 0, "auth_status": {}}))

    base = ["--rules", str(rules), str(report)]
    assert main([*base, "--auth-summary", str(good)]) == 0
    assert main([*base, "--auth-summary", str(good), "--auth-summary", str(bad)]) == 1
    # A scan whose hook never wrote its summary must not pass.
    assert main([*base, "--auth-summary", str(tmp_path / "missing.json")]) == 2
