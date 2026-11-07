#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Opens the seed issues (one per "## N. Title" section, with its "Labels:" line)
# on the public repository. Titles that already exist (open or closed) are skipped,
# so a rerun opens only what is missing. Run apply-settings.sh first: it creates
# the labels.
#
#   scripts/github/open-seed-issues.sh OWNER/REPO [--seeds FILE] [--dry-run]   print (default)
#   scripts/github/open-seed-issues.sh OWNER/REPO [--seeds FILE] --apply       open, after a typed confirmation
#
# FILE defaults to internal/ISSUE_SEEDS.md (private tree only).
set -euo pipefail

# shellcheck source=lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

usage() {
  sed -n '8,11p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' >&2
  exit 2
}

repo="" seeds="$GS_DIR/../../internal/ISSUE_SEEDS.md"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) GS_APPLY=0 ;;
    --apply) GS_APPLY=1 ;;
    --seeds) [[ $# -ge 2 ]] || usage; seeds="$2"; shift ;;
    -h | --help) usage ;;
    -*) echo "unknown option: $1" >&2; usage ;;
    *) [[ -z "$repo" ]] || usage; repo="$1" ;;
  esac
  shift
done
[[ -n "$repo" ]] || { echo "usage: missing OWNER/REPO" >&2; usage; }
gs_valid_repo "$repo" || { echo "usage: '$repo' is not OWNER/REPO" >&2; usage; }
[[ -f "$seeds" ]] || gs_die "seed file not found: $seeds"
gs_need_tools
((GS_APPLY == 0)) || gs_confirm "$repo"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
gs_py seeds "$seeds" --out "$work" >"$work/index.tsv"
# Pull requests are listed here too; a PR with a seed's title also counts.
titles="$(gh api "repos/$repo/issues?state=all&per_page=100" --paginate --jq '.[].title')"

created=0 skipped=0
while IFS=$'\t' read -r body title; do
  if grep -qxF -- "$title" <<<"$titles"; then
    skipped=$((skipped + 1))
    echo "exists: $title"
    continue
  fi
  created=$((created + 1))
  if ((GS_APPLY == 0)); then
    echo "would create: $title"
  else
    echo "create: $title"
    gh api -X POST "repos/$repo/issues" --input "$work/$body" --silent
  fi
done <"$work/index.tsv"
echo "$created to create, $skipped already open"
