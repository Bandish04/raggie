# SPDX-License-Identifier: Apache-2.0
# shellcheck shell=bash
# Shared helpers for the 0.1.0 upgrade scripts (preflight, drain-queues,
# migrate-objectstore). Sourced, never executed. Bash 3.2 compatible so the
# unit tests run on macOS too. Secrets are read from .env but never printed.

UPGRADE_PROJECT="${UPGRADE_PROJECT:-raggie}" # compose project name

# The streams and consumer groups the 0.1.0 workers read (raggie_workers/topics.py).
# shellcheck disable=SC2034 # used by the scripts that source this file
STREAM_GROUPS=(
  "raggie.document.uploaded ingestion-workers"
  "raggie.document.deleted ingestion-workers"
  "raggie.chat.completed eval-workers"
)

log() { printf '[upgrade] %s\n' "$*" >&2; }
die() {
  printf '[upgrade] error: %s\n' "$*" >&2
  exit 1
}

# usage: print the calling script's header comment (after SPDX/shellcheck lines).
usage() {
  awk 'NR > 3 && /^#/ { sub(/^# ?/, ""); print; next } NR > 3 { exit }' "$0"
}

lower() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]'; }

# ── .env parsing (compose rules, without sourcing the file) ───────────────────
# env_get FILE KEY: the value of the LAST assignment of KEY (compose semantics).
# Single/double quotes are stripped; an unquoted value ends at " #".
env_get() {
  local file=$1 key=$2 line value=""
  [[ -f "$file" ]] || return 0
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line#export }"
    [[ "$line" == "$key="* ]] || continue
    value="${line#"$key="}"
    case "$value" in
      \'*) value="${value#\'}" && value="${value%%\'*}" ;;
      \"*) value="${value#\"}" && value="${value%%\"*}" ;;
      *)
        value="$(printf '%s' "$value" | sed -E 's/[[:space:]]+#.*$//; s/[[:space:]]+$//')"
        ;;
    esac
  done <"$file"
  printf '%s' "$value"
}

env_has() { # env_has FILE KEY: KEY is assigned (possibly empty)
  [[ -f "$1" ]] && grep -Eq "^[[:space:]]*(export[[:space:]]+)?$2=" "$1"
}

# ── Secret strength: the union of the edge/control-plane/workers boot checks ──
_KNOWN_DEFAULTS=" raggie raggie-minio change-me-minio minioadmin postgres password admin secret \
change-me dev-insecure-jwt-secret-change-me-please dev-insecure-widget-secret-change-me-please \
change-me-to-a-random-32-byte-min-secret "

# secret_problem VALUE MIN_BYTES: prints why VALUE would be refused, or nothing.
secret_problem() {
  local v=$1 min=$2 l
  l="$(lower "$v")"
  if [[ -z "$v" ]]; then
    printf 'is empty'
  elif [[ "$_KNOWN_DEFAULTS" == *" $l "* ]]; then
    printf 'is a known default'
  elif [[ "$l" == *change-me* || "$l" == *changeme* || "$l" == *dev-insecure* ]]; then
    printf 'is a placeholder'
  elif [[ "$(LC_ALL=C; printf '%s' "${#v}")" -lt "$min" ]]; then
    printf 'is shorter than %s bytes' "$min"
  fi
}

byte_len() { local v=$1; LC_ALL=C; printf '%s' "${#v}"; }

# url_password URL: the percent-decoded password of scheme://user:pass@host.
# Only %XX is decoded; backslashes and a stray % stay as they are.
URL_PCT_RE='^%([0-9A-Fa-f]{2})'
url_password() {
  local rest=${1#*://} userinfo pass out="" c
  [[ "$rest" == *@* ]] || return 0
  userinfo=${rest%%@*}
  [[ "$userinfo" == *:* ]] || return 0
  pass=${userinfo#*:}
  while [[ -n "$pass" ]]; do
    if [[ "$pass" =~ $URL_PCT_RE ]]; then
      printf -v c "\\x${BASH_REMATCH[1]}"
      out+=$c
      pass=${pass:3}
    else
      out+=${pass:0:1}
      pass=${pass:1}
    fi
  done
  printf '%s' "$out"
}

# semver_gt A B: true when A > B (leading "v" ignored, numeric per component).
semver_gt() {
  local a=${1#v} b=${2#v} i x y
  local IFS=.
  # shellcheck disable=SC2206
  local pa=($a) pb=($b)
  for i in 0 1 2; do
    x=${pa[$i]:-0} y=${pb[$i]:-0}
    x=${x%%[!0-9]*} y=${y%%[!0-9]*}
    ((10#${x:-0} > 10#${y:-0})) && return 0
    ((10#${x:-0} < 10#${y:-0})) && return 1
  done
  return 1
}

# ── Redis Streams ─────────────────────────────────────────────────────────────
# parse_xinfo_groups GROUP < `XINFO GROUPS <stream>` (raw redis-cli output):
# prints "<pending> <lag|nil> <last-delivered-id>" for GROUP, nothing if absent.
parse_xinfo_groups() {
  local want=$1 key value name="" pending="" lag="" last="" found=""
  while IFS= read -r key; do
    IFS= read -r value || value=""
    case "$key" in
      name)
        [[ -n "$found" ]] && break
        name=$value pending="" lag="" last=""
        [[ "$name" == "$want" ]] && found=1
        ;;
      pending) pending=$value ;;
      lag) lag=$value ;;
      last-delivered-id) last=$value ;;
    esac
  done
  [[ -n "$found" ]] && printf '%s %s %s' "${pending:-0}" "${lag:-nil}" "$last"
  return 0
}

# parse_xinfo_stream_field FIELD < `XINFO STREAM <stream>`
parse_xinfo_stream_field() {
  local want=$1 key value
  while IFS= read -r key; do
    IFS= read -r value || value=""
    if [[ "$key" == "$want" ]]; then
      printf '%s' "$value"
      return 0
    fi
  done
}

# group_backlog "<pending> <lag> <last-delivered>" <last-generated-id>:
# entries not yet acknowledged + not yet delivered; "unknown" when Redis cannot
# tell (nil lag and the group is behind the stream's last id).
group_backlog() {
  local pending lag last
  read -r pending lag last <<<"$1"
  [[ -z "$pending" ]] && { printf '0'; return; } # no group / no stream
  if [[ "$lag" == nil ]]; then
    if [[ "$last" == "$2" ]]; then lag=0; else printf 'unknown'; return; fi
  fi
  printf '%s' $((pending + lag))
}

# ── Docker (only these touch the host) ────────────────────────────────────────
# compose_container SERVICE [all]: id of the project's container for SERVICE
# (running only unless "all"). Labels work with any compose file version.
compose_container() {
  local flag=()
  [[ "${2:-}" == all ]] && flag=(-a)
  docker ps "${flag[@]}" -q \
    --filter "label=com.docker.compose.project=$UPGRADE_PROJECT" \
    --filter "label=com.docker.compose.service=$1" | head -n1
}

# redis_cli ENV_FILE ARGS...: redis-cli/valkey-cli inside the project's redis
# container. The password goes through REDISCLI_AUTH (never on a command line).
redis_cli() {
  local env_file=$1 cid pw
  shift
  cid="$(compose_container redis)"
  [[ -n "$cid" ]] || die "the $UPGRADE_PROJECT redis container is not running"
  pw="$(env_get "$env_file" REDIS_PASSWORD)"
  [[ -n "$pw" ]] || pw="$(url_password "$(env_get "$env_file" REDIS_URL)")"
  REDISCLI_AUTH="$pw" docker exec -e REDISCLI_AUTH "$cid" sh -c \
    'cli=$(command -v valkey-cli || command -v redis-cli); [ -n "$REDISCLI_AUTH" ] || unset REDISCLI_AUTH; exec "$cli" --no-auth-warning "$@"' \
    redis-cli "$@"
}

# stream_backlog ENV_FILE STREAM GROUP: see group_backlog.
stream_backlog() {
  local groups last
  groups="$(redis_cli "$1" XINFO GROUPS "$2" 2>/dev/null | parse_xinfo_groups "$3")"
  last="$(redis_cli "$1" XINFO STREAM "$2" 2>/dev/null | parse_xinfo_stream_field last-generated-id)"
  group_backlog "$groups" "$last"
}

# volume_kb VOLUME IMAGE: disk usage of a docker volume in KiB (read-only mount).
volume_kb() {
  docker run --rm --network none --entrypoint du -v "$1:/v:ro" "$2" -sk /v 2>/dev/null |
    awk '{print $1}'
}
