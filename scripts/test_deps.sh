#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT}/.test-deps.env"
COMPOSE_FILE="${ROOT}/deploy/compose/docker-compose.test-deps.yml"
PROJECT_NAME="raggie-test-deps"

pick_port() {
  local start="$1"
  python3 - "$start" <<'PY'
import socket
import sys

port = int(sys.argv[1])
for candidate in range(port, port + 200):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("0.0.0.0", candidate))
        except OSError:
            continue
        print(candidate)
        break
else:
    raise SystemExit("no free port found")
PY
}

write_env_file() {
  local pg_port redis_port qdrant_port
  pg_port="$(pick_port "${TEST_POSTGRES_PORT:-55432}")"
  redis_port="$(pick_port "${TEST_REDIS_PORT:-56379}")"
  qdrant_port="$(pick_port "${TEST_QDRANT_PORT:-56333}")"

  cat >"${ENV_FILE}" <<EOF
TEST_POSTGRES_PORT=${pg_port}
TEST_REDIS_PORT=${redis_port}
TEST_QDRANT_PORT=${qdrant_port}
TEST_DATABASE_URL=postgresql://raggie:raggie@localhost:${pg_port}/raggie
TEST_REDIS_URL=redis://localhost:${redis_port}
TEST_QDRANT_URL=http://localhost:${qdrant_port}
EOF
}

compose_cmd() {
  docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" --project-name "${PROJECT_NAME}" "$@"
}

reset_compose_state() {
  compose_cmd down -v --remove-orphans >/dev/null 2>&1 || true
}

cmd="${1:-}"
case "${cmd}" in
  up)
    if [[ ! -f "${ENV_FILE}" ]]; then
      write_env_file
    elif [[ -z "$(compose_cmd ps --status running --services 2>/dev/null)" ]]; then
      write_env_file
    fi
    if ! compose_cmd up -d --wait --remove-orphans; then
      reset_compose_state
      write_env_file
      compose_cmd up -d --wait --remove-orphans
    fi
    ;;
  down)
    if [[ -f "${ENV_FILE}" ]]; then
      compose_cmd down -v --remove-orphans
    else
      docker compose -f "${COMPOSE_FILE}" --project-name "${PROJECT_NAME}" down -v --remove-orphans
    fi
    rm -f "${ENV_FILE}"
    ;;
  logs)
    if [[ ! -f "${ENV_FILE}" ]]; then
      echo "missing ${ENV_FILE}; run '$0 up' first" >&2
      exit 1
    fi
    compose_cmd logs -f --tail=100
    ;;
  env)
    if [[ ! -f "${ENV_FILE}" ]]; then
      echo "missing ${ENV_FILE}; run '$0 up' first" >&2
      exit 1
    fi
    cat "${ENV_FILE}"
    ;;
  *)
    echo "usage: $0 {up|down|logs|env}" >&2
    exit 1
    ;;
esac
