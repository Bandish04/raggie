#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Plain-bash tests for scripts/backup.sh and scripts/restore.sh (no Docker, no
# network: compose, docker and curl are PATH/--compose shims in fakes/).
#
#   scripts/tests/backup/run.sh [filter]
#
# Each test_* function runs in its own subshell with `set -euo pipefail` and a
# fresh temp dir $T holding a minimal install (.env) and the fake object store.
set -uo pipefail

TESTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$TESTS_DIR/../../.." && pwd)"
export TESTS_DIR REPO_ROOT

pass=0 fail=0
failed=()

fail_test() { printf 'ASSERTION FAILED: %s\n' "$*" >&2; exit 1; }
assert_eq() { [[ "$1" == "$2" ]] || fail_test "${3:-values differ}: got '$1', want '$2'"; }
assert_contains() { [[ "$1" == *"$2"* ]] || fail_test "${3:-missing}: '$2' not in: $1"; }
assert_not_contains() { [[ "$1" != *"$2"* ]] || fail_test "${3:-unexpected}: '$2' found"; }
file_mode() { stat -c '%a' "$1" 2>/dev/null || stat -f '%Lp' "$1"; }
# expect_fail CMD... — CMD must exit non-zero; its output lands in $FAIL_OUT.
# shellcheck disable=SC2034 # FAIL_OUT is read by the tests
expect_fail() {
  if FAIL_OUT="$( ("$@") 2>&1)"; then fail_test "expected failure: $*"; fi
  return 0
}
export -f fail_test assert_eq assert_contains assert_not_contains file_mode expect_fail

# shellcheck disable=SC2031 # the test runs in a subshell on purpose
run_test() {
  local file="$1" fn="$2" out rc
  out="$( (
    set -euo pipefail
    T="$(mktemp -d)"
    trap 'rm -rf "$T"' EXIT
    export T PATH="$TESTS_DIR/fakes:$PATH"
    export FAKE_LOG="$T/fake.log" FAKE_STATE="$T/state" FAKE_BUCKET_DIR="$T/bucket" \
      FAKE_S3_DIR="$T/offsite" COMPOSE="$TESTS_DIR/fakes/compose"
    mkdir -p "$FAKE_STATE" "$FAKE_BUCKET_DIR/raggie-uploads/uploads/ws1" "$T/install"
    : >"$FAKE_LOG"
    printf 'file one' >"$FAKE_BUCKET_DIR/raggie-uploads/uploads/ws1/a.pdf"
    printf 'file two!' >"$FAKE_BUCKET_DIR/raggie-uploads/uploads/ws1/b.txt"
    cat >"$T/install/.env" <<'ENV'
RAGGIE_ENV=production
POSTGRES_USER=raggie
POSTGRES_DB=raggie
QDRANT_API_KEY=qdrant-secret-key-0123456789abcdef0123
MINIO_ROOT_USER=raggie
MINIO_ROOT_PASSWORD=minio-secret-password-0123456789
MINIO_BUCKET=raggie-uploads
JWT_SECRET=jwt-secret-0123456789abcdef0123456789abcdef
ENV
    cd "$T/install"
    # shellcheck source=/dev/null
    . "$file"
    "$fn"
  ) 2>&1)"
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

filter="${1:-}"
command -v python3 >/dev/null 2>&1 || { echo "python3 is required" >&2; exit 2; }
for file in "$TESTS_DIR"/test_*.sh; do
  printf '%s\n' "$(basename "$file")"
  for fn in $(grep -oE '^test_[a-z0-9_]+\(\)' "$file" | tr -d '()'); do
    [[ -z "$filter" || "$fn" == *"$filter"* ]] || continue
    run_test "$file" "$fn"
  done
done
printf '\n%d passed, %d failed\n' "$pass" "$fail"
((fail == 0)) || { printf '  %s\n' "${failed[@]}"; exit 1; }
