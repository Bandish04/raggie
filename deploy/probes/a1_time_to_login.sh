#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# A1 acceptance gate: time-to-login < 45 s from a post-pull `compose up`
# (profile core). Measures wall-clock from bringing the core stack up to the
# first successful auth round-trip (web /login served AND control-plane login OK).
#
# Usage:  deploy/probes/a1_time_to_login.sh
# Env:    BUDGET_SECONDS (default 45), WEB_URL, CP_URL, ADMIN_EMAIL/PASSWORD,
#         RESTART=1 to `down` first for a true cold measurement.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
compose() { docker compose -f "${ROOT}/deploy/compose/docker-compose.yml" --env-file "${ROOT}/.env" "$@"; }
BUDGET_SECONDS="${BUDGET_SECONDS:-45}"
WEB_URL="${WEB_URL:-http://127.0.0.1:3000}"
CP_URL="${CP_URL:-http://127.0.0.1:8000}"
ADMIN_EMAIL="${ADMIN_EMAIL:?set ADMIN_EMAIL to an existing admin account}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:?set ADMIN_PASSWORD for ADMIN_EMAIL}"

if [[ "${RESTART:-0}" == "1" ]]; then
  echo "==> bringing the core stack down for a cold measurement"
  compose --profile core down >/dev/null 2>&1 || true
fi

start=$(date +%s)
echo "==> compose up (profile core)"
compose --profile core up -d >/dev/null

deadline=$((start + BUDGET_SECONDS + 30)) # allow polling past the budget to report the real number
login_ok=""
while [[ $(date +%s) -lt $deadline ]]; do
  web_code=$(curl -s -o /dev/null -w "%{http_code}" "${WEB_URL}/login" || echo 000)
  if [[ "$web_code" == "200" ]]; then
    tok=$(curl -s -X POST "${CP_URL}/api/v1/auth/login" -H 'Content-Type: application/json' \
      -d "{\"email\":\"${ADMIN_EMAIL}\",\"password\":\"${ADMIN_PASSWORD}\"}" \
      | grep -o '"access_token"' || true)
    if [[ -n "$tok" ]]; then login_ok=1; break; fi
  fi
  sleep 1
done

elapsed=$(( $(date +%s) - start ))
if [[ -z "$login_ok" ]]; then
  echo "FAIL: login never succeeded within $((BUDGET_SECONDS + 30))s"
  exit 1
fi

echo "==> time-to-login: ${elapsed}s (budget ${BUDGET_SECONDS}s)"
if [[ $elapsed -le $BUDGET_SECONDS ]]; then
  echo "A1 PASS"
else
  echo "A1 FAIL: ${elapsed}s > ${BUDGET_SECONDS}s"
  exit 1
fi
