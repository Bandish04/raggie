#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Tests for scripts/github/apply-settings.sh and open-seed-issues.sh against a
# fake `gh` (tests/fakes/gh) that records every call. No network, no GitHub.
#
#   scripts/github/tests/run.sh [filter]
set -uo pipefail

TESTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$TESTS_DIR/../../.." && pwd)"
export TESTS_DIR REPO_ROOT

pass=0 fail=0
failed=()

fail_test() { printf 'ASSERTION FAILED: %s\n' "$*" >&2; exit 1; }
assert_contains() { [[ "$1" == *"$2"* ]] || fail_test "'$2' not in output:"$'\n'"$1"; }
assert_not_contains() { [[ "$1" != *"$2"* ]] || fail_test "'$2' unexpectedly in output:"$'\n'"$1"; }
expect_fail() {
  if FAIL_OUT="$( ("$@") 2>&1)"; then fail_test "expected failure: $*"; fi
  return 0
}
export -f fail_test assert_contains assert_not_contains expect_fail

# shellcheck disable=SC2031 # the test runs in a subshell on purpose
run_test() {
  local fn="$1" out rc
  # Subshell inside the substitution so its stderr is captured too.
  out="$( (
    set -euo pipefail
    T="$(mktemp -d)"
    trap 'rm -rf "$T"' EXIT
    GH_LOG="$T/gh.log" GH_STATE="$T/state"
    mkdir -p "$GH_STATE"
    : >"$GH_LOG"
    PATH="$TESTS_DIR/fakes:$PATH"
    export T GH_LOG GH_STATE PATH
    # shellcheck source=test_github.sh
    . "$TESTS_DIR/test_github.sh"
    "$fn"
  ) 2>&1 )"
  rc=$?
  if ((rc == 0)); then
    pass=$((pass + 1))
    printf '  ok    %s\n' "$fn"
  else
    fail=$((fail + 1))
    failed+=("$fn")
    printf '  FAIL  %s\n' "$fn"
    printf '%s\n' "$out" | sed 's/^/        | /'
  fi
}

filter="${1:-}"
for tool in jq python3 uv; do
  command -v "$tool" >/dev/null || { echo "$tool is required" >&2; exit 2; }
done
for fn in $(grep -oE '^test_[a-z0-9_]+\(\)' "$TESTS_DIR/test_github.sh" | tr -d '()'); do
  [[ -z "$filter" || "$fn" == *"$filter"* ]] || continue
  run_test "$fn"
done
printf '\n%d passed, %d failed\n' "$pass" "$fail"
((fail == 0)) || { printf '  %s\n' "${failed[@]}"; exit 1; }
