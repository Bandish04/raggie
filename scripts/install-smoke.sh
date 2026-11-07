#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Clean-install smoke test (plan Faz 10), driven by
# .github/workflows/install-smoke.yml. It runs the real installer on a fresh
# host, so it needs Docker and ports 80/443 — run it in CI, not on a laptop.
#
#   scripts/install-smoke.sh prebuild    build the images the install will use (cache warm-up)
#   scripts/install-smoke.sh install     fresh `install.sh --source .`; times start -> login reachable (A1)
#   scripts/install-smoke.sh bootstrap   first admin + workspace through the setup token
#   scripts/install-smoke.sh golden      upload a sample-corpus doc, ask its golden question, assert citations
#   scripts/install-smoke.sh upgrade     re-run the installer; .env unchanged except appended keys; still healthy
#   scripts/install-smoke.sh facts       record host/Docker facts
#   scripts/install-smoke.sh report      write the collected results to the job summary
#   scripts/install-smoke.sh logs DIR    compose ps/logs into DIR
#   scripts/install-smoke.sh down        tear the stack down (volumes included)
#
# Env: SMOKE_EMBEDDINGS=local|cloud (cloud = custom preset against
# scripts/ha/mock_embeddings.py on SMOKE_MOCK_EMBEDDINGS_URL), SMOKE_STATE
# (state dir, default $RUNNER_TEMP/install-smoke), GITHUB_STEP_SUMMARY.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE="${SMOKE_STATE:-${RUNNER_TEMP:-/tmp}/install-smoke}"
EMBEDDINGS="${SMOKE_EMBEDDINGS:-local}"
GOLDEN_DOC="${SMOKE_GOLDEN_DOC:-examples/sample-corpus/kalite-yonetimi/Kalite_Metrikleri_2026_Q3.txt}"
GOLDEN_ID="${SMOKE_GOLDEN_ID:-kal-009}"
mkdir -p "$STATE"
chmod 700 "$STATE"

# shellcheck source=../deploy/scripts/lib.sh
. "$ROOT/deploy/scripts/lib.sh"

log() { printf '\033[1;34m==>\033[0m %s\n' "$*" >&2; }
die() {
  printf '::error::%s\n' "$*" >&2
  exit 1
}
# Result rows collect in the state dir; `report` renders them as one table.
summary() { printf '%s\n' "$*" >>"$STATE/summary.rows"; }
envv() { r_env_get "$ROOT/.env" "$1"; }
now() { date +%s; }

compose() { "$ROOT/.raggie/compose" "$@"; }

# until_ok SECONDS CMD... — retry CMD every 2 s.
until_ok() {
  local deadline=$(($(now) + $1))
  shift
  until "$@" >/dev/null 2>&1; do
    (($(now) < deadline)) || return 1
    sleep 2
  done
}

front() { printf 'http://127.0.0.1:%s' "$(envv HTTP_PORT)"; }
cp_url() { printf 'http://127.0.0.1:%s' "$(envv CONTROL_PLANE_PORT)"; }

install_args() {
  local -a a=(--source "$ROOT" --yes --llm mock --embeddings "$EMBEDDINGS")
  if [[ "$EMBEDDINGS" == cloud ]]; then
    a+=(--embeddings-preset custom --embeddings-base-url "${SMOKE_MOCK_EMBEDDINGS_URL:?}"
      --embeddings-model mock-embed --embedding-dim 1024 --reranker-preset none
      --accept-data-transfer)
  fi
  printf '%s\n' "${a[@]}"
}

# The installer prints the setup token; keep it out of the (public) CI log.
run_installer() { bash "$ROOT/web/public/install.sh" "$@"; }
masked() { sed -E 's/(Setup token: +)[0-9a-f]+/\1***/' "$1"; }

cmd_prebuild() {
  local bake=dense,sparse,rerank
  [[ "$EMBEDDINGS" == local ]] || bake=sparse
  log "building images (EMBEDDINGS_BAKE=$bake)"
  local t0 rc=0
  t0=$(now)
  # Compose loads the services' env_file (.env) even to build; a throwaway copy
  # keeps the real install a fresh one.
  [[ ! -e "$ROOT/.env" ]] || die ".env exists before the clean install"
  cp "$ROOT/.env.example" "$ROOT/.env"
  EMBEDDINGS_BAKE="$bake" docker compose --project-directory "$ROOT" \
    -f "$ROOT/deploy/compose/docker-compose.yml" -f "$ROOT/deploy/compose/docker-compose.demo.yml" \
    --env-file "$ROOT/.env" --profile core --profile mock build || rc=$?
  rm -f "$ROOT/.env"
  ((rc == 0)) || die "image build failed"
  summary "| image build | $(($(now) - t0)) s |"
}

login_reachable() {
  curl -fsS -o /dev/null "$(front)/login" && curl -fsS -o /dev/null "$(cp_url)/readyz"
}

cmd_install() {
  [[ ! -f "$ROOT/.env" ]] || die ".env already exists: not a clean install"
  local -a args
  mapfile -t args < <(install_args)
  local t0 t1 a1 rc=0
  t0=$(now)
  run_installer "${args[@]}" >"$STATE/install.log" 2>&1 || rc=$?
  t1=$(now)
  masked "$STATE/install.log"
  ((rc == 0)) || die "installer failed (exit $rc)"
  until_ok 300 login_reachable || die "login not reachable through the front door"
  a1=$(($(now) - t0))
  cp -p "$ROOT/.env" "$STATE/env.after-install"
  grep -q "Setup token:  $(envv SETUP_TOKEN)" "$STATE/install.log" || die "installer did not print the setup token"
  grep -q "Onboarding:   $(envv PUBLIC_WEB_URL)/onboarding" "$STATE/install.log" || die "installer did not print the onboarding URL"
  log "installer $((t1 - t0))s, login reachable after ${a1}s"
  summary "| installer run (images cached) | $((t1 - t0)) s |"
  summary "| **A1: start -> login reachable** | **${a1} s** (budget 45 s) |"
  printf '%s\n' "$a1" >"$STATE/a1_seconds"
}

# json EXPR — evaluate a Python expression over the JSON on stdin (`d`).
json() { python3 -c "import json,sys; d=json.load(sys.stdin); print($1)"; }

cmd_bootstrap() {
  local token ws resp
  until_ok 120 curl -fsS -o /dev/null "$(cp_url)/readyz" || die "control-plane not ready"
  resp="$(python3 - "$(envv SETUP_TOKEN)" <<'PY' | curl -fsS -X POST "$(cp_url)/api/v1/onboarding/bootstrap" -H 'Content-Type: application/json' --data-binary @-
import json, sys
import secrets
print(json.dumps({"email": "smoke-admin@example.com",
                  "password": "Smoke-" + secrets.token_hex(12) + "-Aa1!",
                  "org_name": "Install Smoke", "setup_token": sys.argv[1]}))
PY
)" || die "bootstrap with the setup token failed"
  token="$(json 'd["access_token"]' <<<"$resp")"
  printf 'Authorization: Bearer %s\n' "$token" >"$STATE/auth.hdr"
  chmod 600 "$STATE/auth.hdr"
  resp="$(curl -fsS -X POST "$(cp_url)/api/v1/onboarding/workspace" -H @"$STATE/auth.hdr" \
    -H 'Content-Type: application/json' -d '{"type":"INTERNAL","name":"smoke"}')" || die "workspace setup failed"
  ws="$(json 'd["workspace"]["id"]' <<<"$resp")"
  printf '%s\n' "$ws" >"$STATE/workspace_id"
  log "admin + workspace $ws created"
}

doc_status() { # DOC_ID -> status
  curl -fsS "$(cp_url)/api/v1/admin/workspaces/$(cat "$STATE/workspace_id")/documents" -H @"$STATE/auth.hdr" |
    python3 -c "import json,sys; print(next((d['status'] for d in json.load(sys.stdin) if d['id']==sys.argv[1]), 'MISSING'))" "$1"
}

cmd_golden() {
  local ws doc_id status deadline question expected t0 body
  ws="$(cat "$STATE/workspace_id")"
  doc_id="$(curl -fsS -X POST "$(cp_url)/api/v1/admin/workspaces/$ws/documents" -H @"$STATE/auth.hdr" \
    -F "file=@$ROOT/$GOLDEN_DOC" | json 'd["id"]')" || die "upload failed"
  log "uploaded $(basename "$GOLDEN_DOC") as $doc_id"
  t0=$(now)
  deadline=$((t0 + ${SMOKE_INGEST_TIMEOUT:-900}))
  while :; do
    status="$(doc_status "$doc_id" || echo ERROR)"
    case "$status" in
      SUCCESS | READY) break ;;
      FAILED) die "ingestion FAILED for $(basename "$GOLDEN_DOC")" ;;
    esac
    (($(now) < deadline)) || die "ingestion still $status after ${SMOKE_INGEST_TIMEOUT:-900}s"
    sleep 5
  done
  summary "| ingest $(basename "$GOLDEN_DOC") | $(($(now) - t0)) s |"

  # The golden entry's question and first expected document (no YAML lib needed).
  expected="$(python3 - "$ROOT/examples/golden/golden.yaml" "$GOLDEN_ID" "$STATE/question" <<'PY'
import re, sys
text = open(sys.argv[1], encoding="utf-8").read()
block = text.split(f'- id: "{sys.argv[2]}"', 1)[1].split("\n  - id:", 1)[0]
open(sys.argv[3], "w", encoding="utf-8").write(re.search(r'^\s+question: "(.*)"$', block, re.M).group(1))
print(re.search(r'^\s+expected_documents: \["([^"]+)"', block, re.M).group(1))
PY
)" || die "golden question $GOLDEN_ID not found"
  question="$(cat "$STATE/question")"
  log "golden $GOLDEN_ID: $question (expects $expected)"
  body="$(python3 -c 'import json,sys; print(json.dumps({"workspace_id": sys.argv[1], "message": sys.argv[2]}))' "$ws" "$question")"
  # Through the front door: Caddy routes /api/v1/chat/* to the edge.
  curl -fsS -N -X POST "$(front)/api/v1/chat/stream" -H @"$STATE/auth.hdr" \
    -H 'Content-Type: application/json' --data-binary "$body" -m 180 >"$STATE/answer.sse" ||
    die "chat stream through the front door failed"
  python3 - "$STATE/answer.sse" "$expected" <<'PY' || die "golden answer check failed (see answer.sse)"
import json, re, sys
raw = open(sys.argv[1], encoding="utf-8").read()
expected = sys.argv[2]
events, answer, sources = [], "", []
for block in raw.split("\n\n"):
    name, data = "message", ""
    for line in block.splitlines():
        if line.startswith("event: "):
            name = line[7:]
        elif line.startswith("data: "):
            data += line[6:]
    if not data:
        continue
    events.append(name)
    payload = json.loads(data)
    if name == "sources":
        sources = payload.get("sources") or []
    elif name == "message" and "delta" in payload:
        answer += payload["delta"]
names = [s.get("filename", "") for s in sources]
print(f"answer: {answer!r}")
print(f"sources: {names}")
assert "done" in events, f"stream ended without `done` (events: {events})"
assert "error" not in events, "stream carried an error event"
assert sources, "no sources: retrieval returned nothing"
assert expected in names, f"expected document {expected} not among the sources"
assert re.search(r"\[\d+\]", answer), "answer has no [n] citation"
PY
  summary "| golden $GOLDEN_ID | ok: cited answer, \`$expected\` retrieved |"
}

cmd_upgrade() {
  local -a args
  mapfile -t args < <(install_args)
  local before="$STATE/env.after-install"
  [[ -f "$before" ]] || die "no post-install .env snapshot"
  local rc=0
  run_installer "${args[@]}" >"$STATE/upgrade.log" 2>&1 || rc=$?
  masked "$STATE/upgrade.log"
  ((rc == 0)) || die "installer re-run failed (exit $rc)"
  grep -q "upgrade mode" "$STATE/upgrade.log" || die "re-run did not detect upgrade mode"
  # Every original line stays byte-identical and in place; the only allowed
  # difference is a block appended by the installer.
  python3 - "$before" "$ROOT/.env" <<'PY' || die ".env changed beyond appended keys"
import sys
old = open(sys.argv[1], "rb").read()
new = open(sys.argv[2], "rb").read()
if new == old:
    print(".env byte-identical")
    sys.exit(0)
if not new.startswith(old):
    sys.exit("existing .env content was modified")
tail = new[len(old):].decode()
marker = "# ── Added by the Raggie installer"
if marker not in tail.split("\n", 2)[1]:
    sys.exit(f"unexpected appended content:\n{tail}")
print(f"appended keys only:\n{tail}")
PY
  until_ok 300 login_reachable || die "stack unhealthy after the upgrade run"
  curl -fsS -o /dev/null "$(front)/healthz" || die "front door /healthz failed after upgrade"
  summary "| upgrade re-run | ok: .env preserved, stack healthy |"
}

cmd_logs() {
  local dir="${1:-$STATE/logs}"
  mkdir -p "$dir"
  compose ps -a >"$dir/ps.txt" 2>&1 || true
  compose logs --no-color --timestamps --tail=2000 >"$dir/compose.log" 2>&1 || true
  cp "$STATE"/*.log "$STATE/answer.sse" "$dir/" 2>/dev/null || true
}

cmd_facts() {
  summary "| host | $(uname -m), $(nproc) vCPU, $(free -g | awk '/^Mem:/ {print $2}') GB RAM, $(df -h --output=avail / | tail -1 | tr -d ' ') free disk |"
  summary "| docker | $(docker version --format '{{.Server.Version}}'), compose $(docker compose version --short) |"
}

cmd_report() {
  local out="${GITHUB_STEP_SUMMARY:-/dev/stdout}"
  {
    printf '### %s · %s embeddings · mock LLM\n\n| step | result |\n|---|---|\n' "${SMOKE_OS:-$(uname -s)}" "$EMBEDDINGS"
    cat "$STATE/summary.rows" 2>/dev/null || true
  } >>"$out"
}

cmd_down() {
  if [[ -x "$ROOT/.raggie/compose" ]]; then
    compose down -v --remove-orphans || true
  fi
}

case "${1:-}" in
  facts | prebuild | install | bootstrap | golden | upgrade | report | down) "cmd_$1" ;;
  logs) cmd_logs "${2:-}" ;;
  *) r_usage "$0"; exit 2 ;;
esac
