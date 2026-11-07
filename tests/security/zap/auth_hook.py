# SPDX-License-Identifier: Apache-2.0
"""ZAP packaged-scan hook (`--hook=/zap/wrk/auth_hook.py`): proof of authentication.

ZAP's JSON report has no request headers, so it cannot show whether the scan
actually sent the bearer. Before ZAP shuts down, this hook walks the message
history and writes, to $ZAP_AUTH_CHECK_OUT (default /zap/wrk/auth-check.json):

    {"total": <messages>, "with_auth": <requests carrying Authorization>,
     "auth_status": {"<status>": <count>, ...}}   # statuses of those requests

assert_report.py --auth-summary fails the job when no request carried the
header, or none of those got a 2xx (the token was ignored or rejected).
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter

_AUTH = re.compile(r"^authorization\s*:", re.IGNORECASE | re.MULTILINE)
_STATUS = re.compile(r"^HTTP/\S+\s+(\d{3})")
_PAGE = 200


def summarize(messages: list[dict]) -> dict:
    statuses: Counter[str] = Counter()
    with_auth = 0
    for msg in messages:
        if not _AUTH.search(msg.get("requestHeader", "")):
            continue
        with_auth += 1
        match = _STATUS.match(msg.get("responseHeader", ""))
        statuses[match.group(1) if match else "none"] += 1
    return {"total": len(messages), "with_auth": with_auth, "auth_status": dict(statuses)}


def zap_pre_shutdown(zap) -> None:  # called by zap_common.trigger_hook
    total = int(zap.core.number_of_messages())
    messages: list[dict] = []
    for start in range(1, total + 1, _PAGE):
        page = zap.core.messages(start=str(start), count=str(_PAGE))
        # Only the headers are needed; drop bodies right away.
        messages += [
            {
                "requestHeader": m.get("requestHeader", ""),
                "responseHeader": m.get("responseHeader", ""),
            }
            for m in page
        ]
    out = os.environ.get("ZAP_AUTH_CHECK_OUT", "/zap/wrk/auth-check.json")
    with open(out, "w") as fh:
        json.dump(summarize(messages), fh)
