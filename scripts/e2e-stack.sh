#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Throwaway full stack for the web e2e suite (web/e2e/stack, `pnpm e2e:stack`).
#
#   eval "$(scripts/e2e-stack.sh up)"   # build + start, then export E2E_* vars
#   (cd web && pnpm e2e:stack)
#   scripts/e2e-stack.sh down           # stop and delete volumes
#
# Other subcommands: env (print the E2E_* exports again), config (render the
# merged compose config without starting anything), logs [service...].
#
# The stack runs with RAGGIE_ENV=production and freshly generated strong
# secrets (incl. SETUP_TOKEN, Redis auth and the Qdrant API key), the `mock`
# profile's deterministic LLM (LLMAAS_BASE_URL=http://mockllm:11435/v1), its own
# compose project (raggie-e2e) and its own host ports, so it never touches the
# repo's .env or a dev stack running alongside it. The browser goes through the
# Caddy front door (E2E_BASE_URL = E2E_PUBLIC_URL = http://localhost:$E2E_HTTP_PORT,
# which also serves the widget); E2E_EDGE_URL and E2E_CONTROL_PLANE_URL are the loopback
# debug ports, for API-level checks. Generated files live in
# $RAGGIE_E2E_DIR (default: ~/.cache/raggie-e2e), outside the repo.
#
# Extra settings (benchmarks, debugging) are applied last, so they win over the
# defaults above. Both feed the app services and compose interpolation:
#   E2E_EXTRA_ENV_FILE=bench.env scripts/e2e-stack.sh up   # KEY=VALUE lines, # comments
#   E2E_ENV_RATE_LIMIT_ENABLED=false E2E_ENV_MOCKLLM_TOKEN_DELAY_MS=0 scripts/e2e-stack.sh up
# (E2E_ENV_<KEY>=value sets KEY; it is applied after the file.)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$REPO_ROOT/deploy/compose/docker-compose.yml"
PROJECT="${RAGGIE_E2E_PROJECT:-raggie-e2e}"
STATE_DIR="${RAGGIE_E2E_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/raggie-e2e}"
APP_ENV="$STATE_DIR/app.env"           # container environment (all app services)
COMPOSE_ENV="$STATE_DIR/compose.env"   # compose interpolation (+ host ports)
OVERRIDE="$STATE_DIR/compose.override.yml"

# Host ports (override via env). Chosen to stay clear of a default dev stack.
HTTP_PORT="${E2E_HTTP_PORT:-8380}"     # Caddy front door (the origin under test)
HTTPS_PORT="${E2E_HTTPS_PORT:-8743}"   # Caddy TLS port (unused: no RAGGIE_DOMAIN)
WEB_PORT="${E2E_WEB_PORT:-3310}"       # loopback debug ports below
EDGE_PORT="${E2E_EDGE_PORT:-8090}"
CONTROL_PLANE_PORT="${E2E_CONTROL_PLANE_PORT:-58000}"
POSTGRES_PORT="${E2E_POSTGRES_PORT:-55432}"
REDIS_PORT="${E2E_REDIS_PORT:-56379}"
QDRANT_HTTP_PORT="${E2E_QDRANT_HTTP_PORT:-56333}"
QDRANT_GRPC_PORT="${E2E_QDRANT_GRPC_PORT:-56334}"
MINIO_API_PORT="${E2E_MINIO_API_PORT:-59000}"

# Services that read the shared env file (compose `env_file: ../../.env`).
# web is deliberately absent: it gets an explicit, secret-free `environment:`
# list in compose (interpolated from the compose env), never the whole env file.
APP_SERVICES=(edge control-plane embeddings ingestion-worker eval-worker scheduler-worker)

die() { echo "e2e-stack: $*" >&2; exit 1; }

random_hex() { openssl rand -hex 32; }
random_b64url() { openssl rand -base64 32 | tr '+/' '-_' | tr -d '\n'; }

# set_kv FILE KEY VALUE — replace KEY=… in FILE, or append it.
set_kv() {
  local file="$1" key="$2" value="$3" tmp
  tmp="$(mktemp "$STATE_DIR/.kv.XXXXXX")"
  awk -v k="$key" -v v="$value" '
    BEGIN { done = 0 }
    index($0, k "=") == 1 { if (!done) { print k "=" v; done = 1 } next }
    { print }
    END { if (!done) print k "=" v }
  ' "$file" >"$tmp"
  mv "$tmp" "$file"
}

get_kv() { grep -E "^$2=" "$1" | tail -n1 | cut -d= -f2-; }

# The Caddy origin the browser (and the widget snippet) use.
front_door() { echo "http://localhost:${HTTP_PORT}"; }

valid_key() { [[ "$1" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; }

# apply_extra_env FILE — E2E_EXTRA_ENV_FILE lines, then E2E_ENV_<KEY> variables.
apply_extra_env() {
  local file="$1" line key name n=0
  if [[ -n "${E2E_EXTRA_ENV_FILE:-}" ]]; then
    [[ -f "$E2E_EXTRA_ENV_FILE" ]] || die "E2E_EXTRA_ENV_FILE not found: $E2E_EXTRA_ENV_FILE"
    while IFS= read -r line || [[ -n "$line" ]]; do
      n=$((n + 1))
      line="${line%$'\r'}"
      [[ "$line" =~ ^[[:space:]]*(#|$) ]] && continue
      key="${line%%=*}"
      [[ "$line" == *=* ]] && valid_key "$key" || die "$E2E_EXTRA_ENV_FILE:$n: expected KEY=VALUE"
      set_kv "$file" "$key" "${line#*=}"
    done <"$E2E_EXTRA_ENV_FILE"
  fi
  for name in $(compgen -v E2E_ENV_ || true); do
    key="${name#E2E_ENV_}"
    valid_key "$key" || die "invalid variable name: $name"
    set_kv "$file" "$key" "${!name}"
  done
}

compose() {
  docker compose -p "$PROJECT" -f "$COMPOSE_FILE" -f "$OVERRIDE" --env-file "$COMPOSE_ENV" \
    --profile core --profile mock "$@"
}

generate() {
  command -v openssl >/dev/null || die "openssl is required"
  mkdir -p "$STATE_DIR"
  chmod 700 "$STATE_DIR"
  umask 077

  # Container env: the documented defaults, then strong per-run secrets.
  cp "$REPO_ROOT/.env.example" "$APP_ENV"
  local pg_pw redis_pw
  pg_pw="$(random_hex)"
  redis_pw="$(random_hex)"
  set_kv "$APP_ENV" RAGGIE_ENV production
  set_kv "$APP_ENV" POSTGRES_PASSWORD "$pg_pw"
  set_kv "$APP_ENV" DATABASE_URL "postgresql://raggie:${pg_pw}@postgres:5432/raggie"
  set_kv "$APP_ENV" REDIS_PASSWORD "$redis_pw"
  set_kv "$APP_ENV" REDIS_URL "redis://:${redis_pw}@redis:6379/0"
  set_kv "$APP_ENV" QDRANT_API_KEY "$(random_hex)"
  set_kv "$APP_ENV" MINIO_ROOT_PASSWORD "$(random_hex)"
  set_kv "$APP_ENV" JWT_SECRET "$(random_hex)"
  set_kv "$APP_ENV" WIDGET_TOKEN_SECRET "$(random_hex)"
  set_kv "$APP_ENV" INTERNAL_API_SECRET "$(random_hex)"
  set_kv "$APP_ENV" INTEGRATION_ENC_KEY "$(random_b64url)"
  set_kv "$APP_ENV" SETUP_TOKEN "$(random_hex)"
  # Deterministic mock LLM (compose `mock` profile); it ignores the key.
  set_kv "$APP_ENV" LLMAAS_BASE_URL "http://mockllm:11435/v1"
  set_kv "$APP_ENV" LLMAAS_API_KEY "mock"
  # Browser-facing URLs: the Caddy origin on this run's host port.
  set_kv "$APP_ENV" RAGGIE_DOMAIN ""
  set_kv "$APP_ENV" PUBLIC_WEB_URL "$(front_door)"
  set_kv "$APP_ENV" WIDGET_EMBED_BASE_URL "$(front_door)"
  # Plain-HTTP localhost: keep session cookies usable without TLS.
  set_kv "$APP_ENV" COOKIE_SECURE false
  # Every spec signs in from the same IP; keep the per-IP auth limiter out of
  # the way while the per-account lockout (what the suite asserts) stays on.
  set_kv "$APP_ENV" AUTH_RATE_LIMIT_MAX 1000
  set_kv "$APP_ENV" COMPOSE_PROFILES ""
  apply_extra_env "$APP_ENV"

  # Compose interpolation: same values + this run's host ports.
  cp "$APP_ENV" "$COMPOSE_ENV"
  local kv
  for kv in \
    "HTTP_PORT=$HTTP_PORT" "HTTPS_PORT=$HTTPS_PORT" \
    "WEB_PORT=$WEB_PORT" "EDGE_HOST_PORT=$EDGE_PORT" "CONTROL_PLANE_PORT=$CONTROL_PLANE_PORT" \
    "POSTGRES_PORT=$POSTGRES_PORT" "REDIS_PORT=$REDIS_PORT" \
    "QDRANT_HTTP_PORT=$QDRANT_HTTP_PORT" "QDRANT_GRPC_PORT=$QDRANT_GRPC_PORT" \
    "MINIO_API_PORT=$MINIO_API_PORT" \
    "DATASTORE_BIND_HOST=127.0.0.1"; do
    set_kv "$COMPOSE_ENV" "${kv%%=*}" "${kv#*=}"
  done

  # Point every app service at the throwaway env instead of the repo's .env.
  {
    echo "# Generated by scripts/e2e-stack.sh — do not edit."
    echo "services:"
    local svc
    for svc in "${APP_SERVICES[@]}"; do
      echo "  ${svc}:"
      echo "    env_file: !override"
      echo "      - ${APP_ENV}"
    done
  } >"$OVERRIDE"
}

print_env() {
  [[ -f "$APP_ENV" ]] || die "no generated env; run: $0 up"
  cat <<EOF
export E2E_BASE_URL=$(front_door)
export E2E_PUBLIC_URL=$(front_door)
export E2E_EDGE_URL=http://localhost:${EDGE_PORT}
export E2E_CONTROL_PLANE_URL=http://127.0.0.1:${CONTROL_PLANE_PORT}
export E2E_SETUP_TOKEN=$(get_kv "$APP_ENV" SETUP_TOKEN)
EOF
}

usage() {
  sed -n '3,26p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

cmd="${1:-}"
[[ $# -gt 0 ]] && shift
case "$cmd" in
  up)
    command -v docker >/dev/null || die "docker is required"
    generate
    # Progress goes to stderr so `eval "$(… up)"` only sees the exports.
    compose up -d --build --wait "$@" >&2
    # The e2e setup project expects a fresh stack (it performs onboarding).
    rm -rf "$REPO_ROOT/web/e2e/stack/.state"
    print_env
    ;;
  config)
    [[ -f "$OVERRIDE" ]] || generate
    compose config "$@"
    ;;
  env) print_env ;;
  logs)
    [[ -f "$OVERRIDE" ]] || die "no generated env; run: $0 up"
    compose logs "$@"
    ;;
  down)
    [[ -f "$OVERRIDE" ]] || die "nothing to tear down (no generated env in $STATE_DIR)"
    compose down -v --remove-orphans "$@"
    rm -rf "$STATE_DIR" "$REPO_ROOT/web/e2e/stack/.state"
    ;;
  -h | --help | help) usage 0 ;;
  *) usage 1 ;;
esac
