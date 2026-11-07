# SPDX-License-Identifier: Apache-2.0
# shellcheck shell=bash
# Shared helpers for scripts/backup.sh, scripts/restore.sh and scripts/dr-drill.sh.
# Sourced, never executed; bash 3.2 compatible. Secrets are read from the env
# file and reach curl/rclone through a 0600 header file or environment
# variables, never through a command line.

BK_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BK_REPO_ROOT="$(cd "$BK_LIB_DIR/../.." && pwd)"
# shellcheck source=../../deploy/scripts/lib.sh
. "$BK_REPO_ROOT/deploy/scripts/lib.sh"

# shellcheck disable=SC2034 # used by the scripts that source this file
BK_MANIFEST="$BK_LIB_DIR/backup_manifest.py"
BK_RCLONE_IMAGE="${RAGGIE_RCLONE_IMAGE:-rclone/rclone:1.75.2@sha256:2687085f718d3c628f7fdfb77c52a1d344332aed543110bb88088f2c70d43eb5}"
# Application services: a restore refuses to run while any of these is up.
BK_APP_SERVICES=" caddy web edge control-plane ingestion-worker eval-worker scheduler-worker mockllm "
BK_DATASTORES="postgres redis qdrant objectstore"

BK_COMPOSE=()
BK_ENV_FILE=""
BK_TMP=""
BK_NETWORK=""
BK_RCLONE_MOUNTS=()

bk_cleanup() { [[ -z "$BK_TMP" ]] || rm -rf "$BK_TMP"; }

# bk_init ENV_FILE [COMPOSE]: the compose command is COMPOSE (an executable such
# as .raggie/compose), else ./.raggie/compose, else the default from-source one.
bk_init() {
  BK_ENV_FILE="$1"
  [[ -f "$BK_ENV_FILE" ]] || r_die "no env file at $BK_ENV_FILE (run from the install directory or pass --env-file)"
  if [[ -n "${2:-}" ]]; then
    BK_COMPOSE=("$2")
  elif [[ -x .raggie/compose ]]; then
    BK_COMPOSE=("$PWD/.raggie/compose")
  else
    [[ -f deploy/compose/docker-compose.yml ]] ||
      r_die "no .raggie/compose and no deploy/compose/docker-compose.yml here; run from the install directory or pass --compose"
    BK_COMPOSE=(docker compose --project-directory "$PWD" -f deploy/compose/docker-compose.yml
      --env-file "$BK_ENV_FILE" --profile core)
  fi
  BK_TMP="$(mktemp -d)"
  chmod 700 "$BK_TMP"
  trap bk_cleanup EXIT
}

bk_env() { r_env_get "$BK_ENV_FILE" "$1"; }
bk_compose() { "${BK_COMPOSE[@]}" "$@"; }

# bk_service_states: "<service> <state>" per container, from `compose ps -a
# --format json` (one object per line on compose >= 2.21, one array before).
# Fails closed: any error dies, so no caller ever decides on a partial view.
bk_service_states() {
  local out
  out="$(bk_compose ps -a --format json 2>"$BK_TMP/ps.err")" ||
    r_die "cannot read the state of the compose services ($(head -n1 "$BK_TMP/ps.err")); refusing to continue"
  printf '%s' "$out" | python3 -c '
import json, sys
text = sys.stdin.read().strip()
rows = json.loads(text) if text.startswith("[") else [json.loads(l) for l in text.splitlines() if l.strip()]
for r in rows:
    svc, state = r.get("Service"), r.get("State")
    if not svc or not state:
        sys.exit(1)
    print(svc, state.lower())' ||
    r_die "cannot read the state of the compose services (unexpected \`compose ps\` output); refusing to continue"
}

bk_running() { # services with a running container, one per line
  local states
  states="$(bk_service_states)" || exit 1
  awk '$2 == "running" { print $1 }' <<<"$states" | sort -u
}

bk_require_running() { # SERVICE...
  local running svc missing=""
  running="$(bk_running)" || exit 1
  running=" $(tr '\n' ' ' <<<"$running") "
  for svc in "$@"; do
    [[ "$running" == *" $svc "* ]] || missing+=" $svc"
  done
  [[ -z "$missing" ]] || r_die "not running:$missing (start them: <compose> up -d $BK_DATASTORES)"
}

# bk_running_app_services: application services with a container that is not
# exited (restarting, created, paused... count as running); absent is fine.
bk_running_app_services() {
  local states svc state out=""
  states="$(bk_service_states)" || exit 1
  while read -r svc state; do
    [[ -n "$svc" && "$BK_APP_SERVICES" == *" $svc "* ]] || continue
    [[ "$state" == exited || "$state" == dead ]] && continue
    [[ " $out " == *" $svc "* ]] || out+=" $svc"
  done <<<"$states"
  printf '%s' "${out# }"
}

bk_pg_user() { local u; u="$(bk_env POSTGRES_USER)"; printf '%s' "${u:-raggie}"; }
bk_pg_db() { local d; d="$(bk_env POSTGRES_DB)"; printf '%s' "${d:-raggie}"; }

bk_sql() { # SQL → single value (whitespace stripped)
  bk_compose exec -T postgres psql -U "$(bk_pg_user)" -d "$(bk_pg_db)" -tAc "$1" | tr -d '[:space:]'
}

# bk_json_get DOTTED.KEY < json: the value at the key ("" when absent).
bk_json_get() {
  python3 -c '
import json, sys
v = json.load(sys.stdin)
for k in sys.argv[1].split("."):
    v = v.get(k) if isinstance(v, dict) else None
print("" if v is None else v if isinstance(v, str) else json.dumps(v))' "$1"
}

# ── Qdrant (host port, api-key from a 0600 header file) ──────────────────────
bk_qdrant_url() {
  local host port
  host="$(bk_env DATASTORE_BIND_HOST)"
  [[ -z "$host" || "$host" == 0.0.0.0 ]] && host=127.0.0.1
  port="$(bk_env QDRANT_HTTP_PORT)"
  printf 'http://%s:%s' "$host" "${port:-6333}"
}

bk_qdrant() { # METHOD PATH [curl args...]
  local method=$1 path=$2 hdr="$BK_TMP/qdrant.headers"
  shift 2
  if [[ ! -f "$hdr" ]]; then
    (umask 077 && printf 'api-key: %s\n' "$(bk_env QDRANT_API_KEY)" >"$hdr")
  fi
  curl -fsS -m "${BK_QDRANT_TIMEOUT:-900}" -X "$method" -H "@$hdr" "$@" "$(bk_qdrant_url)/$path"
}

BK_COLLECTION_RE='^[A-Za-z0-9_-]+$'
# shellcheck disable=SC2034 # used by scripts/backup.sh
BK_SNAPSHOT_RE='^[A-Za-z0-9._-]+\.snapshot$'

bk_qdrant_collections() { # one validated name per line; dies on any error
  local json names c
  json="$(bk_qdrant GET collections)" || r_die "cannot list the Qdrant collections ($(bk_qdrant_url))"
  names="$(printf '%s' "$json" | python3 -c '
import json, sys
for c in json.load(sys.stdin)["result"]["collections"]:
    print(c["name"])')" || r_die "unexpected answer listing the Qdrant collections"
  for c in $names; do
    [[ "$c" =~ $BK_COLLECTION_RE ]] || r_die "unexpected Qdrant collection name: $c"
  done
  printf '%s' "$names"
}

# ── Object store through a pinned rclone container on the compose network ────
bk_store_env() { # export the rclone remote "store:" (and "offsite:" if configured)
  local endpoint scheme=http user pass
  user="$(bk_env MINIO_ROOT_USER)"
  pass="$(bk_env MINIO_ROOT_PASSWORD)"
  endpoint="$(bk_env MINIO_ENDPOINT)"
  endpoint="${endpoint:-objectstore:9000}"
  [[ "$(bk_env MINIO_USE_SSL | tr '[:upper:]' '[:lower:]')" == true ]] && scheme=https
  export RCLONE_CONFIG_STORE_TYPE=s3 RCLONE_CONFIG_STORE_PROVIDER=Other \
    RCLONE_CONFIG_STORE_ENDPOINT="$scheme://$endpoint" \
    RCLONE_CONFIG_STORE_ACCESS_KEY_ID="$user" RCLONE_CONFIG_STORE_SECRET_ACCESS_KEY="$pass"
  if [[ -n "${BACKUP_S3_ACCESS_KEY_ID:-}" ]]; then
    export RCLONE_CONFIG_OFFSITE_TYPE=s3 RCLONE_CONFIG_OFFSITE_PROVIDER="${BACKUP_S3_PROVIDER:-Other}" \
      RCLONE_CONFIG_OFFSITE_ENDPOINT="${BACKUP_S3_ENDPOINT:-}" \
      RCLONE_CONFIG_OFFSITE_REGION="${BACKUP_S3_REGION:-}" \
      RCLONE_CONFIG_OFFSITE_ACCESS_KEY_ID="$BACKUP_S3_ACCESS_KEY_ID" \
      RCLONE_CONFIG_OFFSITE_SECRET_ACCESS_KEY="${BACKUP_S3_SECRET_ACCESS_KEY:-}"
  fi
}

bk_find_network() {
  local cid
  cid="$(bk_compose ps -q objectstore | head -n1)"
  [[ -n "$cid" ]] || r_die "the objectstore container is not running"
  BK_NETWORK="$(docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}' "$cid" | awk '{print $1}')"
}

# bk_rclone ARGS...: callers only use copy / mkdir / size, so nothing is ever
# deleted at the source or the destination.
bk_rclone() {
  local m name mounts=() envs=()
  for m in "${BK_RCLONE_MOUNTS[@]+"${BK_RCLONE_MOUNTS[@]}"}"; do mounts+=(-v "$m"); done
  for name in $(env | sed -n 's/^\(RCLONE_CONFIG_[A-Z0-9_]*\)=.*/\1/p'); do envs+=(-e "$name"); done
  docker run --rm --network "$BK_NETWORK" "${envs[@]}" "${mounts[@]+"${mounts[@]}"}" \
    "$BK_RCLONE_IMAGE" "$@"
}

BK_SIZE_RE='^[0-9]+ [0-9]+$'
bk_rclone_size() { # REMOTE → "<count> <bytes>"; dies when it cannot tell
  local json out
  json="$(bk_rclone size --json "$1")" || r_die "cannot size $1 in the object store (rclone size failed)"
  out="$(printf '%s' "$json" | python3 -c '
import json, sys
d = json.load(sys.stdin)
print(int(d["count"]), int(d["bytes"]))')" || r_die "unexpected rclone size output for $1 (object store)"
  [[ "$out" =~ $BK_SIZE_RE ]] || r_die "unexpected rclone size output for $1 (object store): $out"
  printf '%s' "$out"
}

bk_require_number() { # NAME VALUE: VALUE must be a non-negative integer
  [[ "$2" =~ ^[0-9]+$ ]] || r_die "unexpected $1: '$2'"
}

bk_installed_version() {
  local v=""
  [[ -f .raggie/state.env ]] && v="$(r_env_get .raggie/state.env RAGGIE_INSTALLED_VERSION)"
  [[ -n "$v" ]] || v="$(git -C "$PWD" describe --tags --always 2>/dev/null || true)"
  printf '%s' "${v:-unknown}"
}
