#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Fail when the web container would receive a backend secret.

    scripts/ci/check_web_env.py [--compose rendered.json] [--k8s rendered.yaml ...]
                                [--allow KEY ...]

The web tier is the internet-facing Next.js app; it talks to the backends with
the user's own token and needs none of their secrets. Inputs are the rendered
deployments: `docker compose ... config --format json` and multi-document YAML
from `kubectl kustomize` / `helm template`. A problem is
  - an env key that names a secret (SECRET, PASSWORD, KEY, TOKEN, ... as an
    underscore-separated word, DATABASE_URL, MINIO_ROOT_*), unless --allow'ed,
  - any secretRef / secretKeyRef on the web container (k8s), or a configMapRef
    whose ConfigMap carries a secret-named key,
  - a value with embedded URL credentials (scheme://user:password@host).
Exit codes: 0 clean, 1 problems, 2 unreadable input.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

_SECRET_WORDS = {
    "SECRET",
    "SECRETS",
    "PASSWORD",
    "PASS",
    "PWD",
    "KEY",
    "TOKEN",
    "CREDENTIALS",
    "PRIVATE",
}
_CREDENTIAL_URL = re.compile(r"://[^/\s@]*:[^/\s@]+@")


def is_secret_name(name: str) -> bool:
    upper = name.upper()
    if upper == "DATABASE_URL" or upper.startswith("MINIO_ROOT"):
        return True
    return bool(_SECRET_WORDS & set(upper.split("_")))


def _env_problems(where: str, env: dict[str, str], allow: set[str]) -> list[str]:
    problems = []
    for key, value in sorted(env.items()):
        if key in allow:
            continue
        if is_secret_name(key):
            problems.append(f"{where}: secret-named key {key}")
        elif isinstance(value, str) and _CREDENTIAL_URL.search(value):
            problems.append(f"{where}: {key} embeds URL credentials")
    return problems


def compose_problems(config: dict, allow: set[str] = frozenset()) -> list[str]:
    web = config.get("services", {}).get("web")
    if web is None:
        return ["compose: no web service in the rendered config"]
    env = web.get("environment") or {}
    if isinstance(env, list):  # ["KEY=value", ...]
        env = dict(item.split("=", 1) if "=" in item else (item, "") for item in env)
    problems = _env_problems("compose web", env, allow)
    if web.get("env_file"):
        problems.append("compose web: env_file is set (it would pass every backend setting)")
    return problems


def _is_web_deployment(doc: dict) -> bool:
    name = doc.get("metadata", {}).get("name", "")
    return doc.get("kind") == "Deployment" and (name == "web" or name.endswith("-web"))


def k8s_problems(rendered: str, allow: set[str] = frozenset()) -> list[str]:
    docs = [d for d in yaml.safe_load_all(rendered) if isinstance(d, dict)]
    configmaps = {
        d["metadata"]["name"]: d.get("data") or {} for d in docs if d.get("kind") == "ConfigMap"
    }
    webs = [d for d in docs if _is_web_deployment(d)]
    if not webs:
        return ["k8s: no web Deployment in the rendered manifests"]
    problems: list[str] = []
    for dep in webs:
        where = f"k8s {dep['metadata']['name']}"
        for c in dep["spec"]["template"]["spec"].get("containers", []):
            for src in c.get("envFrom") or []:
                if "secretRef" in src:
                    problems.append(f"{where}: envFrom secretRef {src['secretRef'].get('name')}")
                if "configMapRef" in src:
                    cm = src["configMapRef"].get("name")
                    problems += _env_problems(
                        f"{where} (ConfigMap {cm})", configmaps.get(cm, {}), allow
                    )
            env: dict[str, str] = {}
            for item in c.get("env") or []:
                if "secretKeyRef" in (item.get("valueFrom") or {}):
                    problems.append(f"{where}: {item['name']} from a secretKeyRef")
                else:
                    env[item["name"]] = item.get("value", "")
            problems += _env_problems(where, env, allow)
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--compose", type=Path, action="append", default=[])
    parser.add_argument("--k8s", type=Path, action="append", default=[])
    parser.add_argument("--allow", action="append", default=[], help="non-secret key to accept")
    args = parser.parse_args(argv)
    allow = set(args.allow)
    problems: list[str] = []
    try:
        for path in args.compose:
            problems += [
                f"{path}: {p}" for p in compose_problems(json.loads(path.read_text()), allow)
            ]
        for path in args.k8s:
            problems += [f"{path}: {p}" for p in k8s_problems(path.read_text(), allow)]
    except (OSError, ValueError, yaml.YAMLError, KeyError) as exc:
        print(f"check_web_env: {exc}", file=sys.stderr)
        return 2
    for p in problems:
        print(f"::error::web env: {p}")
    checked = len(args.compose) + len(args.k8s)
    print(f"check_web_env: {checked} rendering(s), {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
