#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Seed the poisoned red-team corpus into two dedicated workspaces.

    eval "$(python3 tests/security/llm/seed.py)"

Logs in to the control plane as a super admin, creates two INTERNAL workspaces
("redteam-a" with corpus/workspace-a, "redteam-b" with corpus/workspace-b),
uploads the files, waits until every document is SUCCESS and prints the
`export` lines promptfoo.yaml reads. Progress goes to stderr. Stdlib only.

Environment:
  RAGGIE_CP_URL              control plane (default http://127.0.0.1:58000)
  RAGGIE_REDTEAM_EMAIL       super-admin email
  RAGGIE_REDTEAM_PASSWORD    super-admin password
  RAGGIE_REDTEAM_TIMEOUT     seconds to wait for ingestion (default 600)

Never point this at a production workspace you care about: the corpus is
deliberately hostile.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
CORPUS = HERE / "corpus"
MIME = {".md": "text/markdown", ".txt": "text/plain", ".pdf": "application/pdf"}


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def call(
    method: str,
    url: str,
    token: str | None = None,
    body: bytes | None = None,
    content_type: str = "application/json",
) -> object:
    req = urllib.request.Request(url, data=body, method=method)
    if body is not None:
        req.add_header("Content-Type", content_type)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 — operator-supplied URL
            raw = resp.read()
    except urllib.error.HTTPError as err:
        detail = err.read()[:300].decode(errors="replace")
        raise SystemExit(f"{method} {url}: HTTP {err.code}: {detail}") from None
    return json.loads(raw) if raw else None


def upload(cp: str, token: str, workspace_id: str, path: Path) -> dict:
    boundary = uuid.uuid4().hex
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
        f"Content-Type: {MIME.get(path.suffix, 'application/octet-stream')}\r\n\r\n"
    ).encode()
    body = head + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    return call(
        "POST",
        f"{cp}/api/v1/admin/workspaces/{workspace_id}/documents",
        token,
        body,
        f"multipart/form-data; boundary={boundary}",
    )


def main() -> None:
    cp = os.environ.get("RAGGIE_CP_URL", "http://127.0.0.1:58000").rstrip("/")
    email = os.environ.get("RAGGIE_REDTEAM_EMAIL")
    password = os.environ.get("RAGGIE_REDTEAM_PASSWORD")
    if not email or not password:
        raise SystemExit("set RAGGIE_REDTEAM_EMAIL and RAGGIE_REDTEAM_PASSWORD (a super admin)")
    timeout = float(os.environ.get("RAGGIE_REDTEAM_TIMEOUT", "600"))

    token = call(
        "POST",
        f"{cp}/api/v1/auth/login",
        body=json.dumps({"email": email, "password": password}).encode(),
    )["access_token"]
    org_id = call("GET", f"{cp}/api/v1/auth/me", token)["org_id"]
    stamp = time.strftime("%Y%m%d-%H%M%S")

    exports = {"RAGGIE_REDTEAM_TOKEN": token}
    pending: dict[str, tuple[str, str]] = {}  # document id -> (workspace id, filename)
    for key in ("a", "b"):
        ws = call(
            "POST",
            f"{cp}/api/v1/admin/orgs/{org_id}/workspaces",
            token,
            json.dumps({"name": f"redteam-{key} {stamp}", "type": "INTERNAL"}).encode(),
        )
        exports[f"RAGGIE_REDTEAM_WORKSPACE_{key.upper()}"] = ws["id"]
        for path in sorted((CORPUS / f"workspace-{key}").iterdir()):
            if path.is_file() and path.suffix in MIME:
                doc = upload(cp, token, ws["id"], path)
                pending[doc["id"]] = (ws["id"], path.name)
                log(f"uploaded {path.name} -> redteam-{key}")

    deadline = time.monotonic() + timeout
    while pending:
        if time.monotonic() > deadline:
            raise SystemExit(f"timed out waiting for: {sorted(n for _, n in pending.values())}")
        for ws_id in {w for w, _ in pending.values()}:
            for doc in call("GET", f"{cp}/api/v1/admin/workspaces/{ws_id}/documents", token):
                if doc["id"] in pending and doc["status"] in ("SUCCESS", "FAILED"):
                    _, name = pending.pop(doc["id"])
                    if doc["status"] == "FAILED":
                        raise SystemExit(f"ingestion FAILED for {name}: {doc.get('error_message')}")
                    log(f"indexed {name}")
        time.sleep(2)

    for k, v in exports.items():
        print(f"export {k}={v}")


if __name__ == "__main__":
    main()
