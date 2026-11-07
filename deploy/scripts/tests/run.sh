#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Plain-bash test runner for the installer scripts (no bats, no Docker, no
# network: curl is a PATH shim, see fakes/curl).
#
#   deploy/scripts/tests/run.sh            # every test_*.sh
#   deploy/scripts/tests/run.sh embeddings # files whose name matches
#   TEST_FILTER=upgrade deploy/scripts/tests/run.sh
#
# Each test_* function runs in its own subshell with `set -euo pipefail`, a fresh
# temp dir as $T (with .env.example / .env.embeddings.example from the repo),
# RAGGIE_YES=1 and no terminal.
set -uo pipefail

TESTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS_DIR="$(dirname "$TESTS_DIR")"
REPO_ROOT="$(cd "$SCRIPTS_DIR/../.." && pwd)"
export TESTS_DIR SCRIPTS_DIR REPO_ROOT

pass=0 fail=0
failed=()

# ── assertions (used inside tests) ───────────────────────────────────────────
fail_test() { printf 'ASSERTION FAILED: %s\n' "$*" >&2; exit 1; }
assert_eq() { [[ "$1" == "$2" ]] || fail_test "${3:-values differ}: got '$1', want '$2'"; }
assert_match() { [[ "$1" =~ $2 ]] || fail_test "${3:-no match}: '$1' !~ /$2/"; }
assert_contains() { [[ "$1" == *"$2"* ]] || fail_test "${3:-missing}: '$2' not in output"; }
assert_not_contains() { [[ "$1" != *"$2"* ]] || fail_test "${3:-unexpected}: '$2' found"; }
assert_file_mode() {
  local m
  m="$(stat -c '%a' "$1" 2>/dev/null || stat -f '%Lp' "$1")"
  assert_eq "$m" "$2" "mode of $(basename "$1")"
}
env_of() { r_env_get "$T/.env" "$1"; }
keys_of() { r_env_get "$T/.env.embeddings" "$1"; }
# expect_fail CMD... — CMD (run in a subshell) must exit non-zero; stderr in $FAIL_OUT.
# shellcheck disable=SC2034 # FAIL_OUT is read by the tests
expect_fail() {
  if FAIL_OUT="$( ("$@") 2>&1)"; then fail_test "expected failure: $*"; fi
  return 0
}
export -f fail_test assert_eq assert_match assert_contains assert_not_contains assert_file_mode env_of keys_of expect_fail

# shellcheck disable=SC2031 # the test runs in a subshell on purpose
run_test() {
  local file="$1" fn="$2" out rc
  # Subshell inside the substitution so its stderr is captured too.
  out="$( (
    set -euo pipefail
    T="$(mktemp -d)"
    trap 'rm -rf "$T"' EXIT
    export T HOME="$T/home" RAGGIE_YES=1 RAGGIE_TTY=/nonexistent/tty
    export PATH="$TESTS_DIR/fakes:$PATH" FAKE_CURL_LOG="$T/curl.log"
    mkdir -p "$HOME"
    : >"$FAKE_CURL_LOG"
    cp "$REPO_ROOT/.env.example" "$T/.env.example"
    cp "$REPO_ROOT/.env.embeddings.example" "$T/.env.embeddings.example"
    # shellcheck source=../lib.sh
    . "$SCRIPTS_DIR/lib.sh"
    # shellcheck source=../configure-env.sh
    . "$SCRIPTS_DIR/configure-env.sh"
    # shellcheck source=../configure-embeddings.sh
    . "$SCRIPTS_DIR/configure-embeddings.sh"
    # shellcheck source=../configure-llm.sh
    . "$SCRIPTS_DIR/configure-llm.sh"
    # shellcheck source=/dev/null
    . "$file"
    "$fn"
  ) 2>&1 )"
  rc=$?
  if ((rc == 0)); then
    pass=$((pass + 1))
    printf '  ok    %s\n' "$fn"
  else
    fail=$((fail + 1))
    failed+=("$(basename "$file"):$fn")
    printf '  FAIL  %s\n' "$fn"
    printf '%s\n' "$out" | sed 's/^/        | /'
  fi
}

filter="${1:-${TEST_FILTER:-}}"
command -v python3 >/dev/null 2>&1 || { echo "python3 is required by the fake curl" >&2; exit 2; }
for file in "$TESTS_DIR"/test_*.sh; do
  [[ -z "$filter" || "$file" == *"$filter"* ]] || continue
  printf '%s\n' "$(basename "$file")"
  for fn in $(grep -oE '^test_[a-z0-9_]+\(\)' "$file" | tr -d '()'); do
    run_test "$file" "$fn"
  done
done
printf '\n%d passed, %d failed\n' "$pass" "$fail"
((fail == 0)) || { printf '  %s\n' "${failed[@]}"; exit 1; }
