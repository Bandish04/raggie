#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""Prepare the authenticated ZAP API scans against a running e2e stack.

Runs after `scripts/e2e-stack.sh up` and the Playwright `setup` project (which
onboards the stack and saves the admin credentials). It
  1. logs in to the control plane as that admin (bearer for the control-plane
     scan),
  2. creates an EXTERNAL workspace whose widget allow-list is the public origin
     and exchanges that Origin for a widget token (bearer for the edge scan),
  3. writes the scan inputs into OUT_DIR: openapi-cp.json (the control plane's
     own /openapi.json, pointed at the stack, minus the operations that would
     end the scanner's session) and openapi-edge.json (.zap/edge-public.openapi.json
     rendered with the public origin and the workspace id).
Tokens are masked in the Actions log and exported through $GITHUB_ENV
(ZAP_CP_BEARER, ZAP_WIDGET_BEARER); nothing secret is written to OUT_DIR.

Usage: bootstrap.py --out DIR [--state web/e2e/stack/.state/stack.json]
Environment: E2E_CONTROL_PLANE_URL, E2E_PUBLIC_URL (or E2E_BASE_URL).
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
EDGE_SPEC = REPO / ".zap" / "edge-public.openapi.json"
DEFAULT_STATE = REPO / "web" / "e2e" / "stack" / ".state" / "stack.json"

# Operations that would revoke or invalidate the scanner's own bearer mid-scan
# and silently turn the rest of the active scan into an unauthenticated one.
SESSION_KILLERS = frozenset({"/api/v1/auth/logout", "/api/v1/auth/change-password"})


def prepare_cp_spec(spec: dict, server_url: str) -> dict:
    out = copy.deepcopy(spec)
    out["servers"] = [{"url": server_url}]
    out["paths"] = {p: ops for p, ops in out.get("paths", {}).items() if p not in SESSION_KILLERS}
    return out


def render_edge_spec(template: dict, public_url: str, workspace_id: str) -> dict:
    out = copy.deepcopy(template)
    out["servers"] = [{"url": public_url}]
    for ops in out["paths"].values():
        for op in ops.values():
            content = op.get("requestBody", {}).get("content", {}).get("application/json")
            if content:
                content["schema"]["properties"]["workspace_id"]["example"] = workspace_id
    return out


def _request(method: str, url: str, *, body=None, headers=None, expect=(200,)) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            status, raw = resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read()
    if status not in expect:
        raise SystemExit(f"bootstrap: {method} {url} -> {status}: {raw[:300]!r}")
    return json.loads(raw) if raw else {}


def _export(name: str, value: str) -> None:
    """Mask a secret in the Actions log and hand it to later steps."""
    print(f"::add-mask::{value}")
    env_file = os.environ.get("GITHUB_ENV")
    if env_file:
        with open(env_file, "a") as fh:
            fh.write(f"{name}={value}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    args = parser.parse_args(argv)

    cp = os.environ["E2E_CONTROL_PLANE_URL"].rstrip("/")
    public = (os.environ.get("E2E_PUBLIC_URL") or os.environ["E2E_BASE_URL"]).rstrip("/")
    state = json.loads(args.state.read_text())

    login = _request(
        "POST",
        f"{cp}/api/v1/auth/login",
        body={"email": state["adminEmail"], "password": state["adminPassword"]},
    )
    admin = {"Authorization": f"Bearer {login['access_token']}"}
    _export("ZAP_CP_BEARER", login["access_token"])

    ws = _request(
        "POST",
        f"{cp}/api/v1/admin/orgs/{state['orgId']}/workspaces",
        body={"name": f"ZAP widget {int(time.time())}", "type": "EXTERNAL"},
        headers=admin,
        expect=(201,),
    )
    _request(
        "PUT",
        f"{cp}/api/v1/admin/workspaces/{ws['id']}/widget",
        body={"cors_allowed_origins": [public]},
        headers=admin,
    )
    widget = _request(
        "POST",
        f"{public}/api/v1/widget/token",
        body={"workspace_id": ws["id"]},
        headers={"Origin": public},
    )
    _export("ZAP_WIDGET_BEARER", widget["token"])

    args.out.mkdir(parents=True, exist_ok=True)
    spec = _request("GET", f"{cp}/openapi.json")
    (args.out / "openapi-cp.json").write_text(json.dumps(prepare_cp_spec(spec, cp), indent=1))
    edge = render_edge_spec(json.loads(EDGE_SPEC.read_text()), public, ws["id"])
    (args.out / "openapi-edge.json").write_text(json.dumps(edge, indent=1))
    print(f"bootstrap: scan inputs in {args.out} (widget workspace {ws['id']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
