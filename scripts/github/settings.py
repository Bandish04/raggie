# SPDX-License-Identifier: Apache-2.0
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pyyaml==6.0.3",
# ]
# ///
"""Request bodies for scripts/github/apply-settings.sh and open-seed-issues.sh.

    uv run scripts/github/settings.py checks [--workflows DIR]
    uv run scripts/github/settings.py payloads --out DIR [--workflows DIR] [--labels FILE]
                                               [--require-signed-commits] [--no-admin-bypass]
                                               [--owner-type User|Organization]
    uv run scripts/github/settings.py seeds FILE --out DIR

Offline: it only reads the workflow files, labels.tsv and the seed file. The
shell scripts make the `gh api` calls.

Required status checks are the job names (matrix expanded) of the workflows in
REQUIRED_JOBS (DCO is dco.yml's job). A workflow whose pull_request trigger has a paths
filter is left out with a warning: when a PR does not touch those paths the
check never reports and the PR waits for it forever.
"""

from __future__ import annotations

import argparse
import itertools
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]

# (workflow file, job id or None for every job) whose checks gate merges to main.
REQUIRED_JOBS: list[tuple[str, str | None]] = [
    ("ci.yml", None),
    ("docs.yml", "links"),
    ("install-smoke.yml", "installer-tests"),
    ("dco.yml", "dco"),
]
# GitHub Actions' app id: Actions checks are pinned to it so no other app or
# commit status can satisfy them.
GITHUB_ACTIONS_APP_ID = 15368
# Built-in repository role ids used as ruleset bypass actors.
ROLE_MAINTAIN = 2
ROLE_ADMIN = 5

_EXPR = re.compile(r"\$\{\{\s*(.*?)\s*\}\}")


def _warn(msg: str) -> None:
    print(f"settings.py: {msg}", file=sys.stderr)


def _load(path: Path) -> dict:
    with path.open() as f:
        return yaml.safe_load(f) or {}


def _pull_request_trigger(doc: dict) -> tuple[bool, list[str]]:
    """(runs on pull_request, path filters on that trigger)."""
    on = doc.get("on", doc.get(True))  # YAML 1.1 reads a bare `on` as True
    if isinstance(on, str):
        return on == "pull_request", []
    if isinstance(on, list):
        return "pull_request" in on, []
    if not isinstance(on, dict) or "pull_request" not in on:
        return False, []
    trigger = on["pull_request"] or {}
    return True, [k for k in ("paths", "paths-ignore") if k in trigger]


def _runs_on_pull_request(cond: object) -> bool:
    cond = str(cond or "")
    if "github.event_name" not in cond:
        return True
    if re.search(r"github\.event_name\s*!=\s*'pull_request'", cond):
        return False
    if "==" in cond and "'pull_request'" not in cond:
        return False
    return True


def _matrix_combos(matrix: object, job_id: str) -> list[dict]:
    if not isinstance(matrix, dict):
        raise SystemExit(f"settings.py: job {job_id}: a dynamic matrix cannot be expanded")
    keys = [k for k in matrix if k not in ("include", "exclude")]
    combos = [
        dict(zip(keys, values, strict=True))
        for values in itertools.product(*(matrix[k] for k in keys))
    ]
    for excluded in matrix.get("exclude") or []:
        combos = [c for c in combos if not all(c.get(k) == v for k, v in excluded.items())]
    for extra in matrix.get("include") or []:
        matches = [c for c in combos if all(c[k] == extra[k] for k in keys if k in extra)]
        for combo in matches:
            combo.update({k: v for k, v in extra.items() if k not in keys})
        if not matches:
            combos.append(dict(extra))
    return combos


def _job_names(job_id: str, job: dict) -> list[str]:
    name = str(job.get("name") or job_id)
    if "${{" not in name:
        return [name]
    combos = _matrix_combos((job.get("strategy") or {}).get("matrix"), job_id)

    def render(combo: dict) -> str:
        def sub(m: re.Match) -> str:
            expr = m.group(1)
            if not expr.startswith("matrix."):
                raise SystemExit(f"settings.py: job {job_id}: cannot expand '{expr}' in its name")
            return str(combo.get(expr.removeprefix("matrix."), ""))

        return _EXPR.sub(sub, name)

    return [render(c) for c in combos]


def required_checks(workflows: Path) -> list[str]:
    checks: list[str] = []
    for file, only in REQUIRED_JOBS:
        doc = _load(workflows / file)
        on_pr, filters = _pull_request_trigger(doc)
        if not on_pr:
            _warn(f"{file} does not run on pull_request; its jobs are not required")
            continue
        if filters:
            _warn(
                f"{file} has a pull_request {'/'.join(filters)} filter, so its check would "
                "never report on PRs outside those paths and block them; not required "
                "(drop the filter to make it required)"
            )
            continue
        jobs = doc.get("jobs") or {}
        if only is not None and only not in jobs:
            raise SystemExit(f"settings.py: {file} has no job '{only}'")
        for job_id, job in jobs.items():
            if only is not None and job_id != only:
                continue
            if not _runs_on_pull_request(job.get("if")):
                continue
            checks.extend(_job_names(job_id, job))
    return checks


# Actions that a composite action calls internally. GitHub enforces the
# allow-list on them too, but they never appear in a workflow file.
NESTED_ACTIONS = {
    "aquasecurity/trivy-action": ("aquasecurity/setup-trivy",),
}


def third_party_actions(workflows: Path) -> list[str]:
    """Allow-list patterns for every non-GitHub action the workflows use."""
    used: set[str] = set()
    for path in sorted(workflows.glob("*.y*ml")):
        for job in (_load(path).get("jobs") or {}).values():
            refs = [job.get("uses")] + [s.get("uses") for s in job.get("steps") or []]
            for ref in filter(None, refs):
                if ref.startswith(("./", "docker://")):
                    continue
                action = ref.split("@", 1)[0]
                if action.split("/", 1)[0] in ("actions", "github"):
                    continue  # covered by github_owned_allowed
                used.add(f"{action}@*")
                used.update(f"{nested}@*" for nested in NESTED_ACTIONS.get(action, ()))
    return sorted(used)


def _ruleset_main(checks: list[str], *, signed: bool, admin_bypass: bool) -> dict:
    status_checks = [{"context": c, "integration_id": GITHUB_ACTIONS_APP_ID} for c in checks]
    rules: list[dict] = [
        {"type": "deletion"},
        {"type": "non_fast_forward"},
        {"type": "required_linear_history"},
        {
            "type": "pull_request",
            "parameters": {
                "required_approving_review_count": 1,
                "require_code_owner_review": True,
                "dismiss_stale_reviews_on_push": True,
                "require_last_push_approval": False,
                "required_review_thread_resolution": False,
                "allowed_merge_methods": ["squash"],
            },
        },
        {
            "type": "required_status_checks",
            "parameters": {
                "strict_required_status_checks_policy": False,
                "do_not_enforce_on_create": False,
                "required_status_checks": status_checks,
            },
        },
    ]
    if signed:
        rules.append({"type": "required_signatures"})
    # A sole maintainer cannot approve their own PR; admins may merge a PR past
    # the rules ("pull_request" mode), never push to main directly.
    bypass = (
        [{"actor_id": ROLE_ADMIN, "actor_type": "RepositoryRole", "bypass_mode": "pull_request"}]
        if admin_bypass
        else []
    )
    return {
        "name": "main",
        "target": "branch",
        "enforcement": "active",
        "bypass_actors": bypass,
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
        "rules": rules,
    }


def _ruleset_tags(*, org_owned: bool) -> dict:
    # The Maintain role exists only in organization repositories.
    roles = (ROLE_MAINTAIN, ROLE_ADMIN) if org_owned else (ROLE_ADMIN,)
    return {
        "name": "release tags",
        "target": "tag",
        "enforcement": "active",
        "bypass_actors": [
            {"actor_id": role, "actor_type": "RepositoryRole", "bypass_mode": "always"}
            for role in roles
        ],
        "conditions": {"ref_name": {"include": ["refs/tags/v*"], "exclude": []}},
        "rules": [{"type": "creation"}, {"type": "update"}, {"type": "deletion"}],
    }


def _labels(path: Path) -> list[dict]:
    labels = []
    for line in path.read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        name, color, description = line.split("\t")
        labels.append({"name": name, "color": color, "description": description})
    return labels


def _write(out: Path, name: str, body: dict) -> None:
    (out / name).write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n")


def payloads(args: argparse.Namespace) -> None:
    out = Path(args.out)
    checks = required_checks(Path(args.workflows))
    _write(
        out,
        "repo.json",
        {
            "has_discussions": True,
            "has_wiki": False,
            "has_projects": False,
            "allow_squash_merge": True,
            "allow_merge_commit": False,
            "allow_rebase_merge": False,
            "squash_merge_commit_title": "PR_TITLE",
            # Keeps every commit's Signed-off-by line (DCO) in the squashed commit.
            "squash_merge_commit_message": "COMMIT_MESSAGES",
            "delete_branch_on_merge": True,
            "allow_auto_merge": True,
            "web_commit_signoff_required": True,
            "security_and_analysis": {
                "secret_scanning": {"status": "enabled"},
                "secret_scanning_push_protection": {"status": "enabled"},
            },
        },
    )
    _write(
        out,
        "actions.json",
        {
            "enabled": True,
            "allowed_actions": "selected",
            "sha_pinning_required": True,
        },
    )
    _write(
        out,
        "selected-actions.json",
        {
            "github_owned_allowed": True,
            "verified_allowed": False,
            "patterns_allowed": third_party_actions(Path(args.workflows)),
        },
    )
    _write(
        out,
        "workflow.json",
        {
            "default_workflow_permissions": "read",
            "can_approve_pull_request_reviews": False,
        },
    )
    _write(
        out,
        "ruleset-main.json",
        _ruleset_main(
            checks, signed=args.require_signed_commits, admin_bypass=not args.no_admin_bypass
        ),
    )
    _write(out, "ruleset-tags.json", _ruleset_tags(org_owned=args.owner_type == "Organization"))
    labels_dir = out / "labels"
    labels_dir.mkdir(exist_ok=True)
    with (out / "labels.tsv").open("w") as index:
        for i, label in enumerate(_labels(Path(args.labels)), 1):
            _write(labels_dir, f"{i:02d}.json", label)
            index.write(
                f"labels/{i:02d}.json\t{label['name']}\t{label['color']}\t{label['description']}\n"
            )


_SEED = re.compile(r"^## \d+\. (.+)$", re.M)
_LABELS = re.compile(r"^Labels: (.+)$", re.M)


def seeds(args: argparse.Namespace) -> None:
    """One issue body per `## N. Title` section; prints "file<TAB>title"."""
    text = Path(args.file).read_text()
    out = Path(args.out)
    heads = list(_SEED.finditer(text))
    if not heads:
        raise SystemExit(f"settings.py: no '## N. Title' sections in {args.file}")
    for i, head in enumerate(heads, 1):
        end = heads[i].start() if i < len(heads) else len(text)
        section = text[head.end() : end]
        labels_line = _LABELS.search(section)
        if labels_line is None:
            raise SystemExit(f"settings.py: seed '{head.group(1)}' has no Labels: line")
        labels = re.findall(r"`([^`]+)`", labels_line.group(1))
        body = (section[: labels_line.start()] + section[labels_line.end() :]).strip()
        name = f"{i:02d}.json"
        _write(out, name, {"title": head.group(1).strip(), "body": body + "\n", "labels": labels})
        print(f"{name}\t{head.group(1).strip()}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    workflows = str(ROOT / ".github" / "workflows")

    p = sub.add_parser("checks", help="print the required status checks")
    p.add_argument("--workflows", default=workflows)

    p = sub.add_parser("payloads", help="write the settings request bodies")
    p.add_argument("--out", required=True)
    p.add_argument("--workflows", default=workflows)
    p.add_argument("--labels", default=str(ROOT / "scripts" / "github" / "labels.tsv"))
    p.add_argument("--require-signed-commits", action="store_true")
    p.add_argument("--no-admin-bypass", action="store_true")
    p.add_argument("--owner-type", choices=("User", "Organization"), default="User")

    p = sub.add_parser("seeds", help="write one issue body per seed")
    p.add_argument("file")
    p.add_argument("--out", required=True)

    args = parser.parse_args()
    if args.cmd == "checks":
        print("\n".join(required_checks(Path(args.workflows))))
    elif args.cmd == "payloads":
        payloads(args)
    else:
        seeds(args)


if __name__ == "__main__":
    main()
