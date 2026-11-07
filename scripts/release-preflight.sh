#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Read-only release gate: is this tree ready to be tagged VERSION?
#
#   scripts/release-preflight.sh VERSION [--repo DIR] [--only check,check,...]
#
# Prints a PASS/WARN/FAIL table and exits 1 when anything FAILs (2 on a usage
# error). No Docker, no network, a few seconds. Checks:
#   changelog    CHANGELOG.md has a dated, non-empty section for VERSION, as
#                extracted by the awk program in .github/workflows/release.yml
#   git          clean working tree; tag vVERSION absent or on HEAD (with
#                RELEASE_PREFLIGHT_REQUIRE_TAG=1, as release.yml runs it on a
#                tag checkout: the tag must exist and be HEAD)
#   i18n         every web/messages/*.json has en.json's key paths, no duplicates
#                (pnpm i18n:check when web/node_modules exists)
#   config-docs  docs/configuration.md matches .env.example (gen-config-docs --check)
#   spdx         every source file has its SPDX header (spdx.py --check)
#   notices      THIRD_PARTY_NOTICES.md review rows are approved (check_review.py);
#                WARN when it lists darwin/win32 packages (generated on macOS/Windows)
#   forbidden    none of scripts/release/forbidden.txt in shippable files
#                (tracked + untracked-but-not-ignored), text extracted from
#                PDFs and Office documents included; an unreadable file FAILs,
#                a document whose text cannot be extracted WARNs
#   gitleaks     no secret in the full git history (WARN when gitleaks is missing)
#   images       every compose/Helm/k8s image is pinned (no :latest, no bare
#                name; WARN without a digest). Local raggie/* builds are exempt.
#   installer    web/public/install.sh has the RAGGIE_DEFAULT_VERSION line that
#                release.yml pins
set -uo pipefail

HELPER="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/release/preflight_checks.py"
CHECKS="changelog git i18n config-docs spdx notices forbidden gitleaks images installer"
RESULTS=()
row() { RESULTS+=("$1|$2|$3"); } # STATUS CHECK DETAIL

usage() { awk 'NR > 2 && /^#/ { sub(/^# ?/, ""); print; next } NR > 2 { exit }' "$0"; }
die_usage() { printf 'release-preflight: %s\n' "$*" >&2; exit 2; }
first_lines() { head -n "${2:-3}" <<<"$1" | tr '\n' ' ' | sed 's/ *$//'; }

check_changelog() {
  local prog notes heading
  prog="$(python3 "$HELPER" release-awk 2>/dev/null || true)"
  if [[ -z "$prog" ]]; then
    row FAIL changelog "cannot find the release-notes awk program in .github/workflows/release.yml"
    return
  fi
  [[ -f CHANGELOG.md ]] || { row FAIL changelog "CHANGELOG.md is missing"; return; }
  notes="$(awk -v v="$VERSION" "$prog" CHANGELOG.md)"
  heading="$(grep -E "^## +\[?v?${VERSION//./\\.}(\]| |$)" CHANGELOG.md | head -n1)"
  if [[ -z "$heading" ]]; then
    row FAIL changelog "no section for $VERSION in CHANGELOG.md"
  elif ! grep -q '[^[:space:]]' <<<"$notes"; then
    row FAIL changelog "the $VERSION section is empty (release.yml would refuse it)"
  elif [[ "$heading" == *TODO* || ! "$heading" =~ [0-9]{4}-[0-9]{2}-[0-9]{2} ]]; then
    row FAIL changelog "the $VERSION heading has no release date: $heading"
  else
    row PASS changelog "$(grep -c . <<<"$notes") line(s) of release notes"
  fi
}

check_git() {
  local dirty tag_commit head problems=()
  dirty="$(git status --porcelain --untracked-files=normal 2>/dev/null)"
  [[ -z "$dirty" ]] || problems+=("working tree not clean ($(grep -c . <<<"$dirty") path(s): $(first_lines "$dirty" 3))")
  head="$(git rev-parse HEAD 2>/dev/null)" || { row FAIL git "not a git repository"; return; }
  if tag_commit="$(git rev-list -n1 "refs/tags/v$VERSION" 2>/dev/null)" && [[ -n "$tag_commit" ]]; then
    if [[ "$tag_commit" != "$head" ]]; then
      problems+=("tag v$VERSION already exists on another commit (${tag_commit:0:12})")
    fi
    [[ ${#problems[@]} -gt 0 ]] || { row PASS git "clean; v$VERSION points at HEAD"; return; }
  elif [[ "${RELEASE_PREFLIGHT_REQUIRE_TAG:-}" == 1 ]]; then
    problems+=("HEAD is not tagged v$VERSION")
  fi
  if [[ ${#problems[@]} -gt 0 ]]; then
    local IFS=';'
    row FAIL git "${problems[*]}"
  else
    row PASS git "clean; v$VERSION is free to tag at ${head:0:12}"
  fi
}

check_i18n() {
  local out
  if [[ -z "${RELEASE_PREFLIGHT_NO_PNPM:-}" && -d web/node_modules ]] && command -v pnpm >/dev/null; then
    # From inside web/ so corepack honours its packageManager pin.
    if out="$(cd web && pnpm -s i18n:check 2>&1)"; then
      row PASS i18n "pnpm i18n:check"
    else
      row FAIL i18n "pnpm i18n:check failed: $(first_lines "$out" 2)"
    fi
  elif out="$(python3 "$HELPER" i18n web/messages 2>&1)"; then
    row PASS i18n "$out"
  else
    row FAIL i18n "$out"
  fi
}

check_tool() { # CHECK FILE ARGS...: run a repo tool, PASS on exit 0
  local id=$1 file=$2 out
  shift 2
  if [[ ! -f "$file" ]]; then
    row FAIL "$id" "$file is missing"
  elif out="$(python3 "$file" "$@" 2>&1)"; then
    row PASS "$id" "$(tail -n1 <<<"${out:-ok}")"
  else
    row FAIL "$id" "$(first_lines "$out" 3)"
  fi
}

check_notices() {
  check_tool notices scripts/notices/check_review.py
  if [[ -f THIRD_PARTY_NOTICES.md ]] && grep -qE -- '-(darwin|win32)-' THIRD_PARTY_NOTICES.md; then
    row WARN notices-platform "THIRD_PARTY_NOTICES.md lists darwin/win32 packages: regenerate it on Linux (make notices) for the release image"
  fi
}

# check_forbidden: the scan runs in preflight_checks.py on the NUL-separated
# list of shippable files (tracked + untracked-not-ignored), so no file name
# is ever split or globbed; it prints the result rows.
check_forbidden() {
  local rules=scripts/release/forbidden.txt out status id detail
  [[ -f "$rules" ]] || { row FAIL forbidden "$rules is missing"; return; }
  if ! out="$(git ls-files -z --cached --others --exclude-standard | python3 "$HELPER" forbidden "$rules" 2>&1)"; then
    row FAIL forbidden "the scan failed: $(first_lines "$out" 2)"
    return
  fi
  while IFS=$'\t' read -r status id detail; do
    case "$status" in
      PASS | WARN | FAIL) row "$status" "$id" "$detail" ;;
      "") ;;
      *) row FAIL forbidden "unexpected scan output: $status $id $detail" ;;
    esac
  done <<<"$out"
}

check_gitleaks() {
  local bin="${RELEASE_PREFLIGHT_GITLEAKS:-$(command -v gitleaks || true)}" out args=()
  if [[ -z "$bin" || "$bin" == none ]]; then
    row WARN gitleaks "gitleaks not installed; CI scans the history (install it to check locally)"
    return
  fi
  [[ -f .gitleaks.toml ]] && args=(--config .gitleaks.toml)
  if out="$("$bin" git "${args[@]+"${args[@]}"}" --redact --no-banner --exit-code 1 . 2>&1)"; then
    row PASS gitleaks "full history clean"
  else
    row FAIL gitleaks "$(first_lines "$out" 2)"
  fi
}

check_images() {
  local out bad floating
  out="$(python3 "$HELPER" images 2>&1 || true)"
  bad="$(sed -n 's/^BAD	//p' <<<"$out")"
  floating="$(sed -n 's/^FLOAT	//p' <<<"$out")"
  if [[ -n "$bad" ]]; then
    row FAIL images "unpinned (latest or no tag): $(first_lines "$bad" 4)"
  elif grep -v -e '^BAD	' -e '^FLOAT	' <<<"$out" | grep -q .; then
    row FAIL images "image scan failed: $(first_lines "$out" 2)"
  else
    row PASS images "no :latest or untagged images"
  fi
  if [[ -n "$floating" ]]; then
    row WARN images-digest "$(grep -c . <<<"$floating") image(s) without a digest, e.g. $(first_lines "$floating" 2)"
  fi
}

check_installer() {
  local line
  line="$(grep -E '^RAGGIE_DEFAULT_VERSION="[^"]*"$' web/public/install.sh 2>/dev/null | head -n1)"
  if [[ -z "$line" ]]; then
    row FAIL installer "web/public/install.sh has no RAGGIE_DEFAULT_VERSION=\"…\" line for release.yml to pin"
  elif [[ -f .github/workflows/release.yml ]] && ! grep -q 's/^RAGGIE_DEFAULT_VERSION=' .github/workflows/release.yml; then
    row FAIL installer "release.yml no longer pins RAGGIE_DEFAULT_VERSION"
  else
    row PASS installer "$line (release.yml pins it to $VERSION)"
  fi
}

print_table() {
  local r status check detail fails=0 warns=0
  for r in "${RESULTS[@]}"; do
    IFS='|' read -r status check detail <<<"$r"
    printf '%-5s %-18s %s\n' "$status" "$check" "$detail"
    [[ $status == FAIL ]] && fails=$((fails + 1))
    [[ $status == WARN ]] && warns=$((warns + 1))
  done
  printf '\n%d check(s): %d FAIL, %d WARN\n' "${#RESULTS[@]}" "$fails" "$warns"
  [[ $fails -eq 0 ]]
}

main() {
  local repo="" only=""
  VERSION=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --repo) repo=$2 && shift 2 ;;
      --only) only=$2 && shift 2 ;;
      -h | --help) usage && exit 0 ;;
      -*) die_usage "unknown option $1" ;;
      *) VERSION=${1#v} && shift ;;
    esac
  done
  local semver='^[0-9]+\.[0-9]+\.[0-9]+([-+][0-9A-Za-z.-]+)?$'
  [[ "$VERSION" =~ $semver ]] || die_usage "usage: $0 VERSION (e.g. 0.1.0)"
  command -v git >/dev/null || die_usage "git is required"
  command -v python3 >/dev/null || die_usage "python3 is required"
  repo="${repo:-$(git rev-parse --show-toplevel 2>/dev/null)}"
  [[ -n "$repo" && -d "$repo" ]] || die_usage "not inside a git repository (use --repo)"
  cd "$repo" || exit 2
  local c selected="${only//,/ }"
  selected="${selected:-$CHECKS}"
  for c in $selected; do
    [[ " $CHECKS " == *" $c "* ]] || die_usage "unknown check '$c' (checks: $CHECKS)"
  done
  for c in $selected; do
    case "$c" in
      changelog) check_changelog ;;
      git) check_git ;;
      i18n) check_i18n ;;
      config-docs) check_tool config-docs scripts/gen-config-docs.py --check ;;
      spdx) check_tool spdx scripts/license/spdx.py --check ;;
      notices) check_notices ;;
      forbidden) check_forbidden ;;
      gitleaks) check_gitleaks ;;
      images) check_images ;;
      installer) check_installer ;;
    esac
  done
  print_table
}

main "$@"
