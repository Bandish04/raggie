#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Tests for scripts/ci/check-dco.sh against throwaway git repositories.
#
#   scripts/ci/tests/test_check_dco.sh [filter]
set -uo pipefail

TESTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHECK="$(cd "$TESTS_DIR/.." && pwd)/check-dco.sh"
export CHECK

pass=0 fail=0
failed=()

fail_test() { printf 'ASSERTION FAILED: %s\n' "$*" >&2; exit 1; }
assert_contains() { [[ "$1" == *"$2"* ]] || fail_test "'$2' not in output:"$'\n'"$1"; }
assert_not_contains() { [[ "$1" != *"$2"* ]] || fail_test "'$2' unexpectedly in output:"$'\n'"$1"; }

# commit AUTHOR_NAME AUTHOR_EMAIL SUBJECT [TRAILER]: one commit on the current
# branch (each branch writes its own file, so merges never conflict).
commit() {
  local msg="$3" file
  [[ -z "${4:-}" ]] || msg+=$'\n\n'"$4"
  file="$(git branch --show-current).txt"
  echo "$3" >>"$file"
  git add "$file"
  GIT_AUTHOR_NAME="$1" GIT_AUTHOR_EMAIL="$2" GIT_COMMITTER_NAME="$1" GIT_COMMITTER_EMAIL="$2" \
    git -c commit.gpgsign=false commit -q -m "$msg"
}
signed() { commit "Ada Lovelace" ada@example.com "$1" "Signed-off-by: Ada Lovelace <ada@example.com>"; }

# A repo whose base commit (main) is itself unsigned: only BASE..HEAD counts.
new_repo() {
  local dir
  dir="$(mktemp -d "$T/repo.XXXXXX")"
  git init -q -b main "$dir"
  cd "$dir" || exit 1
  commit "Old Author" old@example.com "base without sign-off"
  BASE="$(git rev-parse HEAD)"
  git checkout -q -b feature
}

check() { bash "$CHECK" "$BASE" "$(git rev-parse HEAD)" 2>&1; }

test_signed_commits_pass() {
  new_repo
  signed "one"
  signed "two"
  out="$(check)" || fail_test "expected pass:"$'\n'"$out"
  assert_contains "$out" "2 commit(s) signed off"
}

test_unsigned_commit_fails_and_is_named() {
  new_repo
  signed "fine"
  commit "Ada Lovelace" ada@example.com "forgot the sign-off"
  if out="$(check)"; then fail_test "expected failure:"$'\n'"$out"; fi
  assert_contains "$out" "forgot the sign-off"
  assert_contains "$out" "git rebase --signoff"
  assert_not_contains "$out" "base without sign-off"
}

test_sign_off_must_match_the_author_email() {
  new_repo
  commit "Ada Lovelace" ada@example.com "someone else signed" "Signed-off-by: Bob <bob@example.com>"
  if out="$(check)"; then fail_test "expected failure:"$'\n'"$out"; fi
  assert_contains "$out" "someone else signed"
  # A mention of the address in the body is not a trailer.
  new_repo
  commit "Ada Lovelace" ada@example.com "mentions" "Thanks ada@example.com <ada@example.com>"
  if out="$(check)"; then fail_test "a non-trailer mention passed:"$'\n'"$out"; fi
}

test_email_match_ignores_case() {
  new_repo
  commit "Ada Lovelace" Ada@Example.com "mixed case author" "Signed-off-by: Ada Lovelace <ada@example.com>"
  commit "Ada Lovelace" ada@example.com "mixed case trailer" "Signed-off-by: Ada Lovelace <ADA@Example.COM>"
  out="$(check)" || fail_test "expected pass:"$'\n'"$out"
}

test_merge_commits_are_exempt() {
  new_repo
  signed "on feature"
  git checkout -q main
  commit "Old Author" old@example.com "upstream change" "Signed-off-by: Old Author <old@example.com>"
  git checkout -q feature
  GIT_AUTHOR_NAME=Ada GIT_AUTHOR_EMAIL=ada@example.com GIT_COMMITTER_NAME=Ada \
    GIT_COMMITTER_EMAIL=ada@example.com git -c commit.gpgsign=false merge -q --no-ff -m "merge main" main
  out="$(check)" || fail_test "a merge commit was not exempt:"$'\n'"$out"
}

test_known_bots_are_exempt_but_not_their_names_alone() {
  new_repo
  commit "dependabot[bot]" 49699333+dependabot[bot]@users.noreply.github.com "bump a dependency"
  out="$(check)" || fail_test "dependabot was not exempt:"$'\n'"$out"
  assert_contains "$out" "exempt"
  # The name alone does not exempt a commit: the bot's noreply address is needed too.
  new_repo
  commit "dependabot[bot]" mallory@example.com "pretend to be a bot"
  if out="$(check)"; then fail_test "a fake bot name was exempt:"$'\n'"$out"; fi
}

test_empty_range_passes() {
  new_repo
  out="$(check)" || fail_test "expected pass for an empty range:"$'\n'"$out"
}

test_usage_error_without_arguments() {
  new_repo
  if out="$(bash "$CHECK" 2>&1)"; then fail_test "expected a usage error"; fi
  assert_contains "$out" "usage"
}

# shellcheck disable=SC2031 # the test runs in a subshell on purpose
run_test() {
  local fn="$1" out rc
  out="$( (
    set -euo pipefail
    T="$(mktemp -d)"
    trap 'rm -rf "$T"' EXIT
    export T HOME="$T" GIT_CONFIG_NOSYSTEM=1
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
for fn in $(grep -oE '^test_[a-z0-9_]+\(\)' "${BASH_SOURCE[0]}" | tr -d '()'); do
  [[ -z "$filter" || "$fn" == *"$filter"* ]] || continue
  run_test "$fn"
done
printf '\n%d passed, %d failed\n' "$pass" "$fail"
((fail == 0)) || { printf '  %s\n' "${failed[@]}"; exit 1; }
