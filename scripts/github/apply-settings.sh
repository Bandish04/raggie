#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Applies the public repository's GitHub settings (docs/RELEASING.md, "GitHub
# settings checklist") with `gh api`. Idempotent: rulesets are found by name and
# updated in place, labels are created or corrected, the rest are PUT/PATCH.
#
#   scripts/github/apply-settings.sh OWNER/REPO [--dry-run]   print every write (default)
#   scripts/github/apply-settings.sh OWNER/REPO --apply       make them, after a typed confirmation
#
# Options: --require-signed-commits (adds the required_signatures rule)
#          --no-admin-bypass        (admins cannot merge a PR past the main ruleset)
#
# The dry-run still reads the repository (GET only) to tell creates from
# updates, so it needs `gh auth login` with access to OWNER/REPO.
#
# What it sets:
#   repo      Discussions on, wiki and projects off, squash merge only (the
#             squashed message keeps every Signed-off-by), delete branch on
#             merge, auto-merge, sign-off on web commits
#   security  secret scanning + push protection, private vulnerability
#             reporting, Dependabot alerts + security updates
#   actions   GitHub-owned actions plus the third-party actions the workflows
#             use, SHA pinning required, GITHUB_TOKEN read-only, workflows
#             cannot approve PRs
#   rulesets  "main": PR with 1 approval + code owners, stale approvals
#             dismissed, required checks from the workflow files (settings.py
#             checks, DCO from dco.yml), linear history, no force-push or deletion;
#             "release tags": only admins (and maintainers, in an org repo)
#             create, move or delete v*
#   labels    scripts/github/labels.tsv
set -euo pipefail

# shellcheck source=lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

usage() {
  sed -n '6,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' >&2
  exit 2
}

repo="" py_flags=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) GS_APPLY=0 ;;
    --apply) GS_APPLY=1 ;;
    --require-signed-commits | --no-admin-bypass) py_flags+=("$1") ;;
    -h | --help) usage ;;
    -*) echo "unknown option: $1" >&2; usage ;;
    *) [[ -z "$repo" ]] || usage; repo="$1" ;;
  esac
  shift
done
[[ -n "$repo" ]] || { echo "usage: missing OWNER/REPO" >&2; usage; }
gs_valid_repo "$repo" || { echo "usage: '$repo' is not OWNER/REPO" >&2; usage; }
gs_need_tools
((GS_APPLY == 0)) || gs_confirm "$repo"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
gh api "repos/$repo" --jq .full_name >/dev/null
# User-owned repositories have no Maintain role to name as a bypass actor.
owner_type="$(gh api "users/${repo%%/*}" --jq .type)"
[[ "$owner_type" == Organization ]] || owner_type=User
gs_py payloads --out "$work" --owner-type "$owner_type" "${py_flags[@]+"${py_flags[@]}"}"

if ((GS_APPLY == 0)); then
  echo "dry-run: nothing is changed (pass --apply to make these calls)"
  cat <<EOF
verify before --apply (not yet exercised against GitHub):
- actions/permissions sends sha_pinning_required: true; if GitHub rejects the
  field, the run stops at that call and nothing after it is applied.
- ruleset bypass actors use the built-in repository role ids admin=5 and, in
  organization repositories only, maintain=2 (owner type here: $owner_type).
EOF
fi
echo "== repository settings"
gs_write PATCH "repos/$repo" "$work/repo.json"
echo "== security"
gs_write PUT "repos/$repo/vulnerability-alerts"
gs_write PUT "repos/$repo/automated-security-fixes"
gs_write PUT "repos/$repo/private-vulnerability-reporting"
echo "== actions"
gs_write PUT "repos/$repo/actions/permissions" "$work/actions.json"
gs_write PUT "repos/$repo/actions/permissions/selected-actions" "$work/selected-actions.json"
gs_write PUT "repos/$repo/actions/permissions/workflow" "$work/workflow.json"

echo "== rulesets"
existing="$(gh api "repos/$repo/rulesets?includes_parents=false" --paginate \
  --jq '.[] | select(.source_type == "Repository") | "\(.id)\t\(.name)"')"
for file in ruleset-main.json ruleset-tags.json; do
  name="$(sed -n 's/^  "name": "\(.*\)",$/\1/p' "$work/$file")"
  id="$(awk -F'\t' -v n="$name" '$2 == n {print $1; exit}' <<<"$existing")"
  if [[ -n "$id" ]]; then
    gs_write PUT "repos/$repo/rulesets/$id" "$work/$file"
  else
    gs_write POST "repos/$repo/rulesets" "$work/$file"
  fi
done

echo "== labels"
current="$(gh api "repos/$repo/labels?per_page=100" --paginate \
  --jq '.[] | "\(.name)\t\(.color)\t\(.description // "")"')"
while IFS=$'\t' read -r body name color description; do
  have="$(awk -F'\t' -v n="$name" '$1 == n {print; exit}' <<<"$current")"
  if [[ -z "$have" ]]; then
    gs_write POST "repos/$repo/labels" "$work/$body"
  elif [[ "$have" != "$name"$'\t'"$color"$'\t'"$description" ]]; then
    gs_write PATCH "repos/$repo/labels/$(gs_urlencode "$name")" "$work/$body"
  fi
done <"$work/labels.tsv"

cat <<'EOF'
== by hand (no API for these)
- GHCR: make each ghcr.io package public after the first release pushes it
  (Packages -> Package settings -> Change visibility); packages do not exist
  before that and the REST API cannot change their visibility.
- Discussions: create the Q&A and Ideas categories.
- Signed commits are optional: rerun with --require-signed-commits to require them.
EOF
