#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Tests for scripts/release-preflight.sh: each check against a throwaway git
# repo, clean (PASS) and with a planted violation (FAIL). No network, no Docker.
#
#   scripts/release/tests/run.sh [filter]
set -uo pipefail

TESTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$TESTS_DIR/../../.." && pwd)"
PREFLIGHT="$REPO_ROOT/scripts/release-preflight.sh"
export TESTS_DIR REPO_ROOT PREFLIGHT

pass=0 fail=0
failed=()

fail_test() { printf 'ASSERTION FAILED: %s\n' "$*" >&2; exit 1; }
assert_contains() { [[ "$1" == *"$2"* ]] || fail_test "'$2' not in output:"$'\n'"$1"; }
assert_not_contains() { [[ "$1" != *"$2"* ]] || fail_test "'$2' unexpectedly in output:"$'\n'"$1"; }
export -f fail_test assert_contains assert_not_contains

# shellcheck disable=SC2031 # the test runs in a subshell on purpose
run_test() {
  local fn="$1" out rc
  out="$( (
    set -euo pipefail
    T="$(mktemp -d)"
    trap 'rm -rf "$T"' EXIT
    export T RELEASE_PREFLIGHT_NO_PNPM=1 RELEASE_PREFLIGHT_GITLEAKS=none
    # shellcheck source=fixture.sh
    . "$TESTS_DIR/fixture.sh"
    make_fixture "$T/repo"
    # shellcheck source=test_preflight.sh
    . "$TESTS_DIR/test_preflight.sh"
    "$fn"
  ) 2>&1)"
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
for tool in git python3; do
  command -v "$tool" >/dev/null || { echo "$tool is required" >&2; exit 2; }
done
for fn in $(grep -oE '^test_[a-z0-9_]+\(\)' "$TESTS_DIR/test_preflight.sh" | tr -d '()'); do
  [[ -z "$filter" || "$fn" == *"$filter"* ]] || continue
  run_test "$fn"
done
printf '\n%d passed, %d failed\n' "$pass" "$fail"
((fail == 0)) || { printf '  %s\n' "${failed[@]}"; exit 1; }
