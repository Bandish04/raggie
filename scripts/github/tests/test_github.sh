# SPDX-License-Identifier: Apache-2.0
# shellcheck shell=bash
# shellcheck disable=SC2016 # literal ${{ and backticks are what the tests look for
# Test cases for scripts/github/*.sh. Sourced by run.sh inside a subshell with
# T (temp dir), GH_LOG, GH_STATE, REPO_ROOT and the fake gh first on PATH.

APPLY="$REPO_ROOT/scripts/github/apply-settings.sh"
SEEDS="$REPO_ROOT/scripts/github/open-seed-issues.sh"
SETTINGS_PY="$REPO_ROOT/scripts/github/settings.py"
FIXTURE_SEEDS="$TESTS_DIR/fixtures/seeds.md"
R=owner/repo

mutations() { grep -v '^GET ' "$GH_LOG" || true; }
# Request body of the first logged call matching "METHOD PATH".
body_of() {
  local n
  n="$(grep -nxF "$1" "$GH_LOG" | head -n1 | cut -d: -f1)"
  [[ -n "$n" ]] || fail_test "no call '$1' in:"$'\n'"$(cat "$GH_LOG")"
  cat "$GH_STATE/bodies/$n.json"
}
checks() { uv run --quiet --script "$SETTINGS_PY" checks "$@"; }
# Job display names in a workflow, read with grep/sed (independent of settings.py).
static_job_names() {
  sed -n '/^jobs:/,$p' "$1" | grep -E '^    name: ' | sed -E 's/^    name: //; s/^"(.*)"$/\1/' |
    grep -vF '${{' || true
}

# ── required status checks ───────────────────────────────────────────────────

test_required_checks_match_ci_job_names() {
  local out name static
  out="$(checks 2>/dev/null)"
  static="$(static_job_names "$REPO_ROOT/.github/workflows/ci.yml")"
  [[ -n "$static" ]] || fail_test "no job names read from ci.yml"
  while IFS= read -r name; do
    grep -qxF "$name" <<<"$out" || fail_test "ci.yml job '$name' missing from:"$'\n'"$out"
  done <<<"$static"
  # The python job's name is a matrix template, expanded per service.
  for name in "control-plane (python)" "workers (python)" "embeddings (python)" \
    "relative links + anchors (offline)" DCO; do
    grep -qxF "$name" <<<"$out" || fail_test "'$name' missing from:"$'\n'"$out"
  done
  assert_not_contains "$out" '${{'
  # ci.yml's jobs (the python one once per service), docs.yml's links, dco.yml's DCO.
  local want=$(($(wc -l <<<"$static") + 3 + 1 + 1))
  [[ "$(wc -l <<<"$out" | tr -d ' ')" == "$want" ]] || fail_test "expected $want checks, got:"$'\n'"$out"
}

test_path_filtered_workflows_are_not_required() {
  local out err
  out="$(checks 2>"$T/err")"
  err="$(cat "$T/err")"
  # A required check whose workflow is skipped by a paths filter never reports,
  # and the PR then waits for it forever. install-smoke stays path-filtered (its
  # installer tests also run in ci.yml); docs.yml runs on every PR.
  assert_not_contains "$out" "installer unit tests"
  assert_contains "$err" "install-smoke.yml"
  assert_contains "$err" "paths"
  assert_not_contains "$err" "docs.yml"
}

test_required_checks_follow_the_workflow_files() {
  cp -R "$REPO_ROOT/.github/workflows" "$T/wf"
  sed -i.bak 's/^    name: edge (go)$/    name: edge (golang)/' "$T/wf/ci.yml"
  # docs.yml given a pull_request paths filter: its job stops being required.
  python3 - "$T/wf/docs.yml" <<'EOF'
import sys
p = sys.argv[1]
s = open(p).read()
assert "  pull_request:\n" in s
s = s.replace("  pull_request:\n", '  pull_request:\n    paths: ["**/*.md"]\n', 1)
open(p, "w").write(s)
EOF
  local out
  out="$(checks --workflows "$T/wf" 2>/dev/null)"
  assert_contains "$out" "edge (golang)"
  assert_not_contains "$out" "edge (go)"$'\n'
  assert_not_contains "$out" "relative links + anchors (offline)"
  assert_not_contains "$out" "external links (nightly, non-blocking)"
}

# The DCO check is dco.yml's job (no app): its name comes from the workflow.
test_dco_check_is_the_dco_workflow_job() {
  cp -R "$REPO_ROOT/.github/workflows" "$T/wf"
  sed -i.bak 's/^    name: DCO$/    name: DCO sign-off/' "$T/wf/dco.yml"
  local out
  out="$(checks --workflows "$T/wf" 2>/dev/null)"
  assert_contains "$out" "DCO sign-off"
  grep -qxF DCO <<<"$out" && fail_test "a hard-coded DCO check is still required:"$'\n'"$out"
  return 0
}

# ── apply-settings.sh ─────────────────────────────────────────────────────────

test_dry_run_is_the_default_and_never_mutates() {
  local out
  out="$("$APPLY" "$R" 2>&1)"
  [[ -z "$(mutations)" ]] || fail_test "dry-run mutated:"$'\n'"$(mutations)"
  for call in "PATCH repos/$R" "PUT repos/$R/vulnerability-alerts" \
    "PUT repos/$R/automated-security-fixes" "PUT repos/$R/private-vulnerability-reporting" \
    "PUT repos/$R/actions/permissions" "PUT repos/$R/actions/permissions/selected-actions" \
    "PUT repos/$R/actions/permissions/workflow" "POST repos/$R/rulesets" \
    "POST repos/$R/labels"; do
    assert_contains "$out" "would $call"
  done
  assert_contains "$out" '"required_approving_review_count": 1'
  assert_contains "$out" "GHCR"
  assert_not_contains "$out" "apps/dco"
  assert_contains "$out" "verify before --apply"
  assert_contains "$out" "sha_pinning_required"
}

test_explicit_dry_run_flag_never_mutates() {
  "$APPLY" "$R" --dry-run >/dev/null 2>&1
  [[ -z "$(mutations)" ]] || fail_test "dry-run mutated:"$'\n'"$(mutations)"
}

test_apply_needs_the_typed_repository_name() {
  expect_fail "$APPLY" "$R" --apply <<<"yes"
  assert_contains "$FAIL_OUT" "not confirmed"
  [[ -z "$(mutations)" ]] || fail_test "unconfirmed apply mutated:"$'\n'"$(mutations)"
  expect_fail "$APPLY" "$R" --apply </dev/null
  [[ -z "$(mutations)" ]] || fail_test "apply without input mutated:"$'\n'"$(mutations)"
}

test_repo_argument_is_validated() {
  expect_fail "$APPLY"
  assert_contains "$FAIL_OUT" "usage"
  expect_fail "$APPLY" not-a-repo
  expect_fail "$APPLY" "$R" --frobnicate
  [[ ! -s "$GH_LOG" ]] || fail_test "gh was called:"$'\n'"$(cat "$GH_LOG")"
}

test_apply_makes_the_expected_calls() {
  "$APPLY" "$R" --apply <<<"$R" >"$T/out" 2>&1 || fail_test "apply failed:"$'\n'"$(cat "$T/out")"
  local labels
  labels="$(grep -cvE '^(#|$)' "$REPO_ROOT/scripts/github/labels.tsv")"
  local got want
  got="$(mutations | sort | uniq -c | sed 's/^ *//')"
  want="$(sort <<EOF | uniq -c | sed 's/^ *//'
PATCH repos/$R
PUT repos/$R/vulnerability-alerts
PUT repos/$R/automated-security-fixes
PUT repos/$R/private-vulnerability-reporting
PUT repos/$R/actions/permissions
PUT repos/$R/actions/permissions/selected-actions
PUT repos/$R/actions/permissions/workflow
POST repos/$R/rulesets
POST repos/$R/rulesets
$(for _ in $(seq "$labels"); do echo "POST repos/$R/labels"; done)
EOF
)"
  [[ "$got" == "$want" ]] || fail_test "calls differ:"$'\n'"got:"$'\n'"$got"$'\n'"want:"$'\n'"$want"

  local repo actions selected workflow
  repo="$(body_of "PATCH repos/$R")"
  python3 - "$repo" <<'EOF' || fail_test "repo settings: $repo"
import json, sys
b = json.loads(sys.argv[1])
want = {"has_discussions": True, "has_wiki": False, "has_projects": False,
        "allow_squash_merge": True, "allow_merge_commit": False, "allow_rebase_merge": False,
        "delete_branch_on_merge": True, "allow_auto_merge": True}
assert all(b[k] == v for k, v in want.items()), b
sa = b["security_and_analysis"]
assert sa["secret_scanning"]["status"] == "enabled"
assert sa["secret_scanning_push_protection"]["status"] == "enabled"
EOF
  actions="$(body_of "PUT repos/$R/actions/permissions")"
  assert_contains "$actions" '"allowed_actions": "selected"'
  assert_contains "$actions" '"sha_pinning_required": true'
  selected="$(body_of "PUT repos/$R/actions/permissions/selected-actions")"
  # Every third-party action the workflows use is allow-listed, nothing else.
  local used
  used="$(grep -rhoE 'uses: *[^ ]+' "$REPO_ROOT/.github/workflows" | sed -E 's/uses: *//; s/@.*//' |
    grep -vE '^(actions|github)/|^\./|^docker://' | sort -u)"
  while IFS= read -r a; do assert_contains "$selected" "\"$a@*\""; done <<<"$used"
  [[ "$(grep -c '@\*' <<<"$selected")" == "$(wc -l <<<"$used" | tr -d ' ')" ]] ||
    fail_test "unexpected patterns: $selected"
  workflow="$(body_of "PUT repos/$R/actions/permissions/workflow")"
  assert_contains "$workflow" '"default_workflow_permissions": "read"'
  assert_contains "$workflow" '"can_approve_pull_request_reviews": false'
}

test_rulesets_carry_reviews_checks_and_tag_protection() {
  export GH_OWNER_TYPE=Organization
  "$APPLY" "$R" --apply <<<"$R" >/dev/null 2>&1 || fail_test "apply failed"
  local main tags
  main="$(body_of "POST repos/$R/rulesets")"
  tags="$(sed -n 2p <(grep -nxF "POST repos/$R/rulesets" "$GH_LOG") | cut -d: -f1)"
  tags="$(cat "$GH_STATE/bodies/$tags.json")"
  checks 2>/dev/null >"$T/checks"
  python3 - "$main" "$tags" "$T/checks" <<'EOF' || fail_test "rulesets:"$'\n'"$main"$'\n'"$tags"
import json, sys
main, tags = json.loads(sys.argv[1]), json.loads(sys.argv[2])
want_checks = open(sys.argv[3]).read().split("\n")[:-1]
rules = {r["type"]: r.get("parameters", {}) for r in main["rules"]}
assert main["target"] == "branch" and main["enforcement"] == "active"
assert main["conditions"]["ref_name"]["include"] == ["~DEFAULT_BRANCH"]
assert {"deletion", "non_fast_forward", "required_linear_history"} <= rules.keys()
assert "required_signatures" not in rules  # opt-in
pr = rules["pull_request"]
assert pr["required_approving_review_count"] == 1
assert pr["require_code_owner_review"] is True
assert pr["dismiss_stale_reviews_on_push"] is True
assert pr["allowed_merge_methods"] == ["squash"]
contexts = [c["context"] for c in rules["required_status_checks"]["required_status_checks"]]
assert contexts == want_checks, (contexts, want_checks)
by_ctx = {c["context"]: c for c in rules["required_status_checks"]["required_status_checks"]}
assert by_ctx["edge (go)"]["integration_id"] == 15368  # GitHub Actions only
assert by_ctx["DCO"]["integration_id"] == 15368  # dco.yml, not an app
assert tags["target"] == "tag"
assert tags["conditions"]["ref_name"]["include"] == ["refs/tags/v*"]
assert {r["type"] for r in tags["rules"]} == {"creation", "update", "deletion"}
assert {a["actor_id"] for a in tags["bypass_actors"]} == {2, 5}  # maintain, admin
EOF
}

# A user-owned repository has no Maintain role, so only admins bypass the tag
# ruleset there.
test_user_owned_repo_omits_the_maintain_bypass() {
  export GH_OWNER_TYPE=User
  "$APPLY" "$R" --apply <<<"$R" >"$T/out" 2>&1 || fail_test "apply failed:"$'\n'"$(cat "$T/out")"
  grep -qxF "GET users/owner" "$GH_LOG" || fail_test "owner type not read:"$'\n'"$(cat "$GH_LOG")"
  local n tags
  n="$(grep -nxF "POST repos/$R/rulesets" "$GH_LOG" | sed -n 2p | cut -d: -f1)"
  tags="$(cat "$GH_STATE/bodies/$n.json")"
  python3 - "$tags" <<'EOF' || fail_test "tag ruleset: $tags"
import json, sys
b = json.loads(sys.argv[1])
assert b["name"] == "release tags"
assert [a["actor_id"] for a in b["bypass_actors"]] == [5], b["bypass_actors"]
EOF
}

test_signed_commits_and_strict_admins_are_opt_in() {
  "$APPLY" "$R" --apply --require-signed-commits --no-admin-bypass <<<"$R" >/dev/null 2>&1 ||
    fail_test "apply failed"
  local main
  main="$(body_of "POST repos/$R/rulesets")"
  assert_contains "$main" '"required_signatures"'
  assert_contains "$main" '"bypass_actors": []'
}

test_apply_is_idempotent() {
  "$APPLY" "$R" --apply <<<"$R" >/dev/null 2>&1 || fail_test "first apply failed"
  : >"$GH_LOG"
  "$APPLY" "$R" --apply <<<"$R" >"$T/out" 2>&1 || fail_test "second apply failed:"$'\n'"$(cat "$T/out")"
  local m
  m="$(mutations)"
  assert_not_contains "$m" "POST"
  assert_contains "$m" "PUT repos/$R/rulesets/1"
  assert_contains "$m" "PUT repos/$R/rulesets/2"
  assert_not_contains "$m" "labels"
  [[ "$(jq length "$GH_STATE/rulesets.json")" == 2 ]] || fail_test "ruleset duplicated"
  # A label edited by hand is put back, only that one.
  jq 'map(if .name == "help wanted" then .color = "000000" else . end)' "$GH_STATE/labels.json" \
    >"$T/l" && mv "$T/l" "$GH_STATE/labels.json"
  : >"$GH_LOG"
  "$APPLY" "$R" --apply <<<"$R" >/dev/null 2>&1 || fail_test "third apply failed"
  [[ "$(mutations | grep labels)" == "PATCH repos/$R/labels/help%20wanted" ]] ||
    fail_test "label repair:"$'\n'"$(mutations)"
}

test_apply_stops_on_the_first_failed_call() {
  export GH_FAIL="PUT repos/$R/actions/permissions"
  expect_fail "$APPLY" "$R" --apply <<<"$R"
  assert_not_contains "$(mutations)" "rulesets"
}

test_labels_cover_seeds_and_issue_templates() {
  local tsv used label
  tsv="$(grep -vE '^(#|$)' "$REPO_ROOT/scripts/github/labels.tsv" | cut -f1)"
  used="$(grep -hE '^labels:' "$REPO_ROOT"/.github/ISSUE_TEMPLATE/*.yml | grep -oE '"[^"]+"' | tr -d '"')"
  for f in "$REPO_ROOT/internal/ISSUE_SEEDS.md" "$FIXTURE_SEEDS"; do
    [[ -f "$f" ]] || continue
    used+=$'\n'"$(grep -E '^(Labels|Label set):' "$f" | grep -oE '`[^`]+`' | tr -d '`')"
  done
  while IFS= read -r label; do
    [[ -z "$label" ]] || grep -qxF "$label" <<<"$tsv" || fail_test "label '$label' not in labels.tsv"
  done <<<"$(sort -u <<<"$used")"
  # Colors are 6 hex digits and every label has a description.
  awk -F'\t' '!/^(#|$)/ && (NF != 3 || $2 !~ /^[0-9a-f]{6}$/ || $3 == "") {print; bad=1} END {exit bad}' \
    "$REPO_ROOT/scripts/github/labels.tsv" || fail_test "malformed labels.tsv row"
}

# ── open-seed-issues.sh ───────────────────────────────────────────────────────

test_seed_issues_dry_run_never_mutates() {
  local out
  out="$("$SEEDS" "$R" --seeds "$FIXTURE_SEEDS" 2>&1)"
  [[ -z "$(mutations)" ]] || fail_test "dry-run mutated:"$'\n'"$(mutations)"
  assert_contains "$out" "would create: First seed"
  assert_contains "$out" "would create: Third seed"
  assert_contains "$out" "3 to create, 0 already open"
}

test_seed_issues_apply_skips_existing_titles() {
  echo '[{"title": "Second seed"}, {"title": "unrelated"}]' >"$GH_STATE/issues.json"
  "$SEEDS" "$R" --seeds "$FIXTURE_SEEDS" --apply <<<"$R" >"$T/out" 2>&1 ||
    fail_test "apply failed:"$'\n'"$(cat "$T/out")"
  [[ "$(mutations)" == "POST repos/$R/issues"$'\n'"POST repos/$R/issues" ]] ||
    fail_test "calls:"$'\n'"$(mutations)"
  local first
  first="$(body_of "POST repos/$R/issues")"
  python3 - "$first" <<'EOF' || fail_test "issue body: $first"
import json, sys
b = json.loads(sys.argv[1])
assert b["title"] == "First seed"
assert b["labels"] == ["good first issue", "area:docs"]
assert b["body"].startswith('Context: a "quoted" body with `code` and a \\backslash.')
assert "## 2." not in b["body"] and "Labels:" not in b["body"]
EOF
  : >"$GH_LOG"
  "$SEEDS" "$R" --seeds "$FIXTURE_SEEDS" --apply <<<"$R" >"$T/out" 2>&1 || fail_test "rerun failed"
  [[ -z "$(mutations)" ]] || fail_test "rerun created issues:"$'\n'"$(mutations)"
  assert_contains "$(cat "$T/out")" "0 to create, 3 already open"
}

test_seed_issues_apply_needs_confirmation() {
  expect_fail "$SEEDS" "$R" --seeds "$FIXTURE_SEEDS" --apply <<<"owner/other"
  [[ -z "$(mutations)" ]] || fail_test "unconfirmed apply mutated"
}

test_real_seed_file_has_18_issues() {
  local f="$REPO_ROOT/internal/ISSUE_SEEDS.md"
  if [[ ! -f "$f" ]]; then
    echo "skip: $f not present (private tree only)"
    return 0
  fi
  local out
  out="$("$SEEDS" "$R" --seeds "$f" 2>&1)"
  assert_contains "$out" "18 to create, 0 already open"
  assert_contains "$out" "would create: Ingest CSV files"
  assert_contains "$out" "would create: Kafka/Redpanda event-bus adapter (design doc)"
}
