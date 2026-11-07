# SPDX-License-Identifier: Apache-2.0
# shellcheck shell=bash
# Shared by apply-settings.sh and open-seed-issues.sh: dry-run aware `gh api`
# writes, the typed confirmation and the offline payload builder (settings.py).

GS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GS_APPLY=0 # 1 after --apply; every write is only printed until then

gs_die() { echo "$*" >&2; exit 1; }

gs_need_tools() {
  local tool
  for tool in gh uv; do
    command -v "$tool" >/dev/null || gs_die "$tool is required (gh: https://cli.github.com, uv: https://docs.astral.sh/uv/)"
  done
}

gs_valid_repo() { [[ "$1" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]; }

# Reads the repository name from stdin; anything else stops before any write.
gs_confirm() {
  local repo="$1" answer=""
  printf 'This changes https://github.com/%s.\nType the repository name (%s) to apply: ' "$repo" "$repo" >&2
  IFS= read -r answer || true
  [[ "$answer" == "$repo" ]] || gs_die $'\n'"not confirmed; nothing was changed"
  echo >&2
}

gs_py() { uv run --quiet --script "$GS_DIR/settings.py" "$@"; }

# Percent-encodes a path segment (label names), like jq's @uri.
gs_urlencode() {
  local LC_ALL=C s="$1" out="" c i # bytewise, so UTF-8 is encoded per byte
  for ((i = 0; i < ${#s}; i++)); do
    c="${s:i:1}"
    case "$c" in
      [A-Za-z0-9._~-]) out+="$c" ;;
      *) out+="$(printf '%%%02X' "'$c")" ;;
    esac
  done
  printf '%s' "$out"
}

# gs_write METHOD PATH [BODY_FILE]: prints the call in dry-run, makes it with --apply.
gs_write() {
  local method="$1" path="$2" body="${3:-}"
  if ((GS_APPLY == 0)); then
    printf 'would %s %s\n' "$method" "$path"
    [[ -z "$body" ]] || sed 's/^/    /' "$body"
    return 0
  fi
  printf '%s %s\n' "$method" "$path"
  if [[ -n "$body" ]]; then
    gh api -X "$method" "$path" --input "$body" --silent
  else
    gh api -X "$method" "$path" --silent
  fi
}
