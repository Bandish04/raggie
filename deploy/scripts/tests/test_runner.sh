# SPDX-License-Identifier: Apache-2.0
# shellcheck shell=bash
# The runner itself: a failing test's stderr must reach the report.

test_runner_reports_stderr_of_a_failing_test() {
  local repo="$T/repo" out
  mkdir -p "$repo/deploy/scripts/tests"
  cp "$T/.env.example" "$T/.env.embeddings.example" "$repo/"
  cp "$SCRIPTS_DIR"/*.sh "$repo/deploy/scripts/"
  cp -R "$TESTS_DIR/run.sh" "$TESTS_DIR/fakes" "$repo/deploy/scripts/tests/"
  # Written with printf so this file's own discovery (^test_) does not pick it up.
  printf '%s\n' \
    'test_fails_with_a_stderr_message() {' \
    "  printf 'stderr-sentinel-%s\\n' 42 >&2" \
    '  r_warn "warn-sentinel"' \
    '  return 1' \
    '}' >"$repo/deploy/scripts/tests/test_meta.sh"
  out="$(bash "$repo/deploy/scripts/tests/run.sh" 2>/dev/null)" && fail_test "the failing meta test passed"
  assert_contains "$out" "FAIL  test_fails_with_a_stderr_message"
  assert_contains "$out" "| stderr-sentinel-42" "stderr of the failing test missing from the report"
  assert_contains "$out" "warn-sentinel" "r_warn output missing from the report"
  assert_not_contains "$out" "2>&1)" "shell syntax leaked into captured output"
}
