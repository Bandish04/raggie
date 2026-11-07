#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# shellcheck source-path=SCRIPTDIR
# Read-only pre-upgrade checks for moving a Docker Compose install to 0.1.0.
#
#   scripts/upgrade/0.1.0/preflight.sh [--dir <install dir>] [--env-file <path>] [--no-docker]
#
# Checks .env against the boot-time secret rules of 0.1.0 (the services refuse
# to start otherwise), REDIS_PASSWORD/REDIS_URL consistency, the public URLs
# now that Caddy is the front door, plain-number port variables, free host
# ports 80/443, disk space for the
# object copy and backups, the Qdrant version (0.1.0 pins one; no downgrades),
# the legacy MinIO volume/image, and the Redis stream backlog. Prints a
# PASS/WARN/FAIL table and exits 1 when anything FAILs. Never prints a secret
# and never changes anything (Docker is only queried, plus a throwaway `du`
# container to size volumes).
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$HERE/lib.sh"

QDRANT_TARGET_VERSION="1.20.0" # deploy/compose/docker-compose.yml in 0.1.0
# Latest patch of each minor up to the target. A single-node Qdrant must not
# skip a minor version, and it can never downgrade its storage.
QDRANT_UPGRADE_PATH="1.18.3 1.19.2 1.20.0"
GIB_KB=$((1024 * 1024))

RESULTS=()
result() { RESULTS+=("$1|$2|$3"); }

# ── .env checks (pure: only read the file) ────────────────────────────────────
check_secret() { # check_secret FILE NAME MIN_BYTES [optional|required] [FIX]
  local value problem fix="${5:-}"
  value="$(env_get "$1" "$2")"
  if [[ -z "$value" && "${4:-}" == optional ]]; then
    result PASS "secret $2" "not set (optional)"
    return
  fi
  problem="$(secret_problem "$value" "$3")"
  if [[ -n "$problem" ]]; then
    result FAIL "secret $2" "$problem${fix:+; $fix}"
  else
    result PASS "secret $2" "ok ($(byte_len "$value") bytes)"
  fi
}

check_secrets() {
  local f=$1 env db_url db_pw pg_pw
  env="$(lower "$(env_get "$f" RAGGIE_ENV)")"
  case "$env" in
    development | dev | local | test | testing)
      result WARN secrets "RAGGIE_ENV=$env: the services skip secret checks; set production on a server"
      return
      ;;
    "") result WARN RAGGIE_ENV "empty = production: every secret check below applies" ;;
    production) result PASS RAGGIE_ENV production ;;
    *) result WARN RAGGIE_ENV "unknown value, treated as production" ;;
  esac
  check_secret "$f" JWT_SECRET 32
  check_secret "$f" WIDGET_TOKEN_SECRET 32
  check_secret "$f" INTERNAL_API_SECRET 32 optional
  check_secret "$f" METRICS_TOKEN 32 optional
  check_secret "$f" INTEGRATION_ENC_KEY 32 optional
  check_secret "$f" SETUP_TOKEN 32 optional
  # Same rule as cp, workers and edge: empty is allowed, else >= 32 bytes and no
  # default/placeholder. Qdrant itself holds the key, so it restarts too.
  check_secret "$f" QDRANT_API_KEY 32 optional \
    "rotate QDRANT_API_KEY (and restart Qdrant with the new key)"
  [[ "$(lower "$(env_get "$f" SCIM_ENABLED)")" == true ]] && check_secret "$f" SCIM_BEARER_TOKEN 32
  check_secret "$f" MINIO_ROOT_PASSWORD 16
  db_url="$(env_get "$f" DATABASE_URL)"
  if [[ -z "$db_url" ]]; then
    check_secret "$f" POSTGRES_PASSWORD 16
    result FAIL DATABASE_URL "missing (the edge refuses to start without it)"
    return
  fi
  # With DATABASE_URL set the services check its password; POSTGRES_PASSWORD
  # only seeded the database on first start.
  if [[ -n "$(secret_problem "$(env_get "$f" POSTGRES_PASSWORD)" 16)" ]]; then
    result WARN "secret POSTGRES_PASSWORD" "$(secret_problem "$(env_get "$f" POSTGRES_PASSWORD)" 16) (not checked at boot while DATABASE_URL is set)"
  fi
  db_pw="$(url_password "$db_url")"
  pg_pw="$(env_get "$f" POSTGRES_PASSWORD)"
  if [[ -n "$db_pw" && -n "$(secret_problem "$db_pw" 16)" ]]; then
    result FAIL "secret DATABASE_URL password" "$(secret_problem "$db_pw" 16)"
  elif [[ -n "$db_pw" && -n "$pg_pw" && "$db_pw" != "$pg_pw" ]]; then
    result WARN DATABASE_URL "password differs from POSTGRES_PASSWORD (fine only if intended)"
  else
    result PASS DATABASE_URL set
  fi
}

check_redis() {
  local f=$1 pw url url_pw
  if [[ -n "$(env_get "$f" REDIS_SENTINEL_ADDRS)" ]]; then
    result PASS "REDIS_URL / REDIS_PASSWORD" "Sentinel mode: REDIS_URL unused"
    return
  fi
  pw="$(env_get "$f" REDIS_PASSWORD)"
  url="$(env_get "$f" REDIS_URL)"
  url_pw="$(url_password "$url")"
  if [[ -n "$pw" && -z "$url_pw" ]]; then
    result FAIL "REDIS_URL / REDIS_PASSWORD" \
      "REDIS_PASSWORD is set but REDIS_URL carries no password (use redis://:<password>@redis:6379/0)"
  elif [[ -n "$pw" && "$pw" != "$url_pw" ]]; then
    result FAIL "REDIS_URL / REDIS_PASSWORD" "REDIS_URL carries a different password than REDIS_PASSWORD"
  elif [[ -z "$pw" && -n "$url_pw" ]]; then
    result FAIL "REDIS_URL / REDIS_PASSWORD" \
      "REDIS_URL has a password but REDIS_PASSWORD is empty: Valkey would start without auth"
  elif [[ -z "$pw" ]]; then
    result WARN "REDIS_URL / REDIS_PASSWORD" "no auth: set REDIS_PASSWORD and the same password in REDIS_URL"
  else
    result PASS "REDIS_URL / REDIS_PASSWORD" "consistent (auth on)"
  fi
}

check_public_urls() {
  local f=$1 domain widget web cookie locale
  domain="$(env_get "$f" RAGGIE_DOMAIN)"
  widget="$(env_get "$f" WIDGET_EMBED_BASE_URL)"
  if [[ "$widget" == *:8080* ]]; then
    result FAIL WIDGET_EMBED_BASE_URL \
      "points at the edge port :8080; 0.1.0 serves the widget from the Caddy origin (http://<host> or https://<RAGGIE_DOMAIN>)"
  elif [[ -z "$widget" ]]; then
    result WARN WIDGET_EMBED_BASE_URL "empty: embed snippets fall back to http://localhost"
  elif [[ -n "$domain" && "${widget%/}" != "https://$domain" ]]; then
    result WARN WIDGET_EMBED_BASE_URL "differs from https://$domain (the Caddy origin for RAGGIE_DOMAIN)"
  else
    result PASS WIDGET_EMBED_BASE_URL "on the Caddy origin"
  fi
  web="$(env_get "$f" PUBLIC_WEB_URL)"
  if [[ "$web" == *:3000* ]]; then
    result WARN PUBLIC_WEB_URL "points at :3000; web listens on loopback only in 0.1.0 (use the Caddy origin)"
  fi
  cookie="$(lower "$(env_get "$f" COOKIE_SECURE)")"
  if [[ "$cookie" == true && -z "$domain" ]]; then
    result WARN COOKIE_SECURE "true without RAGGIE_DOMAIN: logins fail over plain HTTP"
  else
    result PASS COOKIE_SECURE "${cookie:-auto}"
  fi
  locale="$(env_get "$f" NEXT_PUBLIC_DEFAULT_LOCALE)"
  if [[ -z "$locale" ]]; then
    result WARN NEXT_PUBLIC_DEFAULT_LOCALE "unset: the UI default becomes en (set tr to keep Turkish)"
  else
    result PASS NEXT_PUBLIC_DEFAULT_LOCALE "$locale"
  fi
}

# Port variables are interpolated into "127.0.0.1:${VAR}:<port>" (and the
# services read some as their listen port), so a host prefix breaks the stack.
check_port_vars() {
  local f=$1 name value
  for name in WEB_PORT CONTROL_PLANE_PORT EDGE_HOST_PORT EDGE_PORT HTTP_PORT HTTPS_PORT; do
    env_has "$f" "$name" || continue
    value="$(env_get "$f" "$name")"
    if [[ -n "$value" && ! "$value" =~ ^[0-9]+$ ]]; then
      result FAIL "$name" "must be a plain port number (0.1.0 already binds web, edge and control-plane to 127.0.0.1)"
    else
      result PASS "$name" "${value:-default}"
    fi
  done
}

# disk_verdict FREE_KB NEEDED_KB: FAIL below one copy + 2 GiB headroom, WARN
# below copy + backup (2x) + 2 GiB.
disk_verdict() {
  if (($1 < $2 + 2 * GIB_KB)); then
    printf FAIL
  elif (($1 < 2 * $2 + 2 * GIB_KB)); then
    printf WARN
  else
    printf PASS
  fi
}

# ── Host / Docker checks ──────────────────────────────────────────────────────
check_ports() {
  local f=$1 port name listener
  for name in HTTP_PORT HTTPS_PORT; do
    port="$(env_get "$f" "$name")"
    [[ -n "$port" ]] || { [[ $name == HTTP_PORT ]] && port=80 || port=443; }
    if [[ -n "$(compose_container caddy)" ]]; then
      result PASS "port $port ($name)" "held by the $UPGRADE_PROJECT caddy container"
      continue
    fi
    if ! command -v ss >/dev/null; then
      result WARN "port $port ($name)" "ss not available; check manually"
      continue
    fi
    listener="$(ss -Hltnp "sport = :$port" 2>/dev/null | head -n1)"
    if [[ -z "$listener" ]]; then
      result PASS "port $port ($name)" free
    elif [[ "$listener" == *caddy* ]]; then
      result FAIL "port $port ($name)" "a host Caddy listens here; stop it (sudo systemctl disable --now caddy) — compose runs its own"
    else
      result FAIL "port $port ($name)" "in use: $(awk '{print $4, $6}' <<<"$listener")"
    fi
  done
}

check_disk() {
  local pg_cid helper root free minio_kb=0 pg_kb=0 needed verdict
  pg_cid="$(compose_container postgres)"
  if [[ -z "$pg_cid" ]]; then
    result WARN disk "postgres is not running; cannot size the volumes"
    return
  fi
  helper="$(docker inspect -f '{{.Config.Image}}' "$pg_cid")"
  docker volume inspect "${UPGRADE_PROJECT}_minio_data" >/dev/null 2>&1 &&
    minio_kb="$(volume_kb "${UPGRADE_PROJECT}_minio_data" "$helper")"
  pg_kb="$(volume_kb "${UPGRADE_PROJECT}_postgres_data" "$helper")"
  root="$(docker info -f '{{.DockerRootDir}}' 2>/dev/null)"
  free="$(df -Pk "${root:-/}" | awk 'NR==2 {print $4}')"
  needed=$((${minio_kb:-0} + ${pg_kb:-0}))
  verdict="$(disk_verdict "$free" "$needed")"
  result "$verdict" disk "$((free / 1024)) MiB free under ${root:-/}; MinIO $((${minio_kb:-0} / 1024)) MiB + Postgres $((${pg_kb:-0} / 1024)) MiB to copy/back up"
}

check_volumes() {
  local cid image
  if docker volume inspect "${UPGRADE_PROJECT}_minio_data" >/dev/null 2>&1; then
    result PASS "volume ${UPGRADE_PROJECT}_minio_data" "present (copy it with migrate-objectstore.sh)"
    cid="$(compose_container minio all)"
    image="${LEGACY_MINIO_IMAGE:-}"
    [[ -z "$image" && -n "$cid" ]] && image="$(docker inspect -f '{{.Image}}' "$cid")"
    if [[ -n "$image" ]] && docker image inspect "$image" >/dev/null 2>&1; then
      result PASS "MinIO image" "cached locally (upstream no longer publishes images)"
    else
      result WARN "MinIO image" "no local MinIO image found; pass --legacy-image to migrate-objectstore.sh"
    fi
  else
    result WARN "volume ${UPGRADE_PROJECT}_minio_data" "absent: nothing to copy (fresh install or external S3)"
  fi
  if docker volume inspect "${UPGRADE_PROJECT}_objectstore_data" >/dev/null 2>&1; then
    result PASS "volume ${UPGRADE_PROJECT}_objectstore_data" "already exists (copy is idempotent)"
  fi
}

# qdrant_verdict RUNNING: prints "STATUS|message" for upgrading RUNNING to
# QDRANT_TARGET_VERSION.
qdrant_verdict() {
  local running=${1#v} t=$QDRANT_TARGET_VERSION hop rmaj rmin hmaj hmin
  rmaj=${running%%.*} rmin=${running#*.}
  rmin=${rmin%%.*}
  if semver_gt "$running" "$t"; then
    echo "FAIL|running $running, 0.1.0 pins $t: Qdrant cannot downgrade its storage; pin $running in the compose file first"
    return
  fi
  for hop in $QDRANT_UPGRADE_PATH; do
    hmaj=${hop%%.*} hmin=${hop#*.}
    hmin=${hmin%%.*}
    [[ "$hmaj" == "$rmaj" ]] && ((10#$hmin <= 10#$rmin)) && continue
    if [[ "$hmaj" != "$rmaj" ]] || ((10#$hmin > 10#$rmin + 1)); then
      echo "FAIL|running $running: a single-node Qdrant cannot skip minor versions; step through the latest patch of every minor up to $t first"
    elif [[ "$hop" != "$t" ]]; then
      echo "FAIL|running $running, 0.1.0 pins $t: start qdrant/qdrant:v$hop on the same volume first (no skipped minor), then upgrade"
    else
      echo "PASS|running $running (0.1.0: $t)"
    fi
    return
  done
  echo "PASS|running $running (0.1.0: $t)"
}

check_qdrant() {
  local f=$1 cid version verdict
  cid="$(compose_container qdrant)"
  if [[ -z "$cid" ]]; then
    result WARN qdrant "not running; cannot read its version"
    return
  fi
  version="$(QDRANT_KEY="$(env_get "$f" QDRANT_API_KEY)" docker exec -e QDRANT_KEY "$cid" bash -c \
    'exec 3<>/dev/tcp/127.0.0.1/6333 && printf "GET / HTTP/1.0\r\napi-key: %s\r\n\r\n" "$QDRANT_KEY" >&3 && cat <&3' \
    2>/dev/null | grep -oE '"version":"[^"]+"' | cut -d'"' -f4)"
  if [[ -z "$version" ]]; then
    result WARN qdrant "could not read the running version"
  else
    verdict="$(qdrant_verdict "$version")"
    result "${verdict%%|*}" qdrant "${verdict#*|}"
  fi
}

check_streams() {
  local f=$1 pair stream group backlog
  if [[ -z "$(compose_container redis)" ]]; then
    result WARN "redis streams" "redis is not running; cannot read the backlog"
    return
  fi
  for pair in "${STREAM_GROUPS[@]}"; do
    read -r stream group <<<"$pair"
    backlog="$(stream_backlog "$f" "$stream" "$group")"
    case "$backlog" in
      0) result PASS "stream $stream" "nothing pending for $group" ;;
      unknown) result WARN "stream $stream" "backlog unknown for $group; run drain-queues.sh" ;;
      *) result WARN "stream $stream" "$backlog entries not yet processed by $group: run drain-queues.sh before switching to Valkey" ;;
    esac
  done
}

print_table() {
  local row status check detail fails=0 warns=0
  printf '%-6s %-34s  %s\n' STATUS CHECK DETAIL
  for row in "${RESULTS[@]}"; do
    IFS='|' read -r status check detail <<<"$row"
    printf '%-6s %-34s  %s\n' "$status" "$check" "$detail"
    [[ $status == FAIL ]] && fails=$((fails + 1))
    [[ $status == WARN ]] && warns=$((warns + 1))
  done
  printf '\n%d check(s): %d FAIL, %d WARN\n' "${#RESULTS[@]}" "$fails" "$warns"
  [[ $fails -eq 0 ]]
}

main() {
  local dir="." env_file="" docker=1
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --dir) dir=$2 && shift 2 ;;
      --env-file) env_file=$2 && shift 2 ;;
      --no-docker) docker=0 && shift ;;
      -h | --help) usage && return 0 ;;
      *) die "unknown option: $1" ;;
    esac
  done
  env_file="${env_file:-$dir/.env}"
  [[ -f "$env_file" ]] || die "no .env at $env_file (use --dir or --env-file)"
  check_secrets "$env_file"
  check_redis "$env_file"
  check_public_urls "$env_file"
  check_port_vars "$env_file"
  if [[ $docker -eq 1 ]]; then
    command -v docker >/dev/null || die "docker not found (or use --no-docker)"
    check_ports "$env_file"
    check_disk
    check_volumes
    check_qdrant "$env_file"
    check_streams "$env_file"
  fi
  print_table
}

if [[ -z "${UPGRADE_LIB_ONLY:-}" ]]; then
  main "$@"
fi
