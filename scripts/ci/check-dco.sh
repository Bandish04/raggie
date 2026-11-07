#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Developer Certificate of Origin check (CONTRIBUTING.md) for a commit range,
# run by .github/workflows/dco.yml on every pull request. Pure git, no app.
#
#   scripts/ci/check-dco.sh BASE HEAD
#
# Every non-merge commit in BASE..HEAD needs a `Signed-off-by:` trailer whose
# address is the commit author's (case-insensitive). Exempt: merge commits and
# the GitHub bots below, matched by name AND their noreply address.
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: check-dco.sh BASE HEAD" >&2
  exit 2
fi
base="$1" head="$2"

EXEMPT_BOTS=("dependabot[bot]" "github-actions[bot]")

is_exempt_bot() {
  local name="$1" email="$2" bot
  for bot in "${EXEMPT_BOTS[@]}"; do
    [[ "$name" == "$bot" && "$email" == *"+$bot@users.noreply.github.com" ]] && return 0
  done
  return 1
}

# The lower-cased addresses of a commit's Signed-off-by trailers, one per line.
signoff_emails() {
  git log -1 --format='%(trailers:key=Signed-off-by,valueonly,separator=%x0A)' "$1" |
    sed -n 's/.*<\([^>]*\)>.*/\1/p' | tr '[:upper:]' '[:lower:]'
}

checked=0 exempt=0 missing=0
while IFS= read -r sha; do
  name="$(git log -1 --format=%an "$sha")"
  email="$(git log -1 --format=%ae "$sha")"
  if is_exempt_bot "$name" "$email"; then
    exempt=$((exempt + 1))
    continue
  fi
  checked=$((checked + 1))
  want="$(tr '[:upper:]' '[:lower:]' <<<"$email")"
  if signoff_emails "$sha" | grep -qxF -- "$want"; then
    continue
  fi
  missing=$((missing + 1))
  subject="$(git log -1 --format=%s "$sha")"
  msg="${sha:0:12} \"$subject\" by $name <$email> has no Signed-off-by: $name <$email>"
  if [[ "${GITHUB_ACTIONS:-}" == true ]]; then
    echo "::error title=DCO::$msg"
  else
    echo "missing sign-off: $msg"
  fi
done < <(git rev-list --no-merges "$base..$head")

if ((missing > 0)); then
  cat <<EOF

$missing of $checked commit(s) lack a sign-off matching their author.
Sign them off and force-push (see CONTRIBUTING.md, "Developer Certificate of Origin"):
  git rebase --signoff $base
  git push --force-with-lease
EOF
  exit 1
fi
echo "DCO: $checked commit(s) signed off, $exempt exempt (bots); merge commits are not checked."
