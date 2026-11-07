#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# shellcheck source-path=SCRIPTDIR
# Disaster-recovery drill: back up a seeded stack, restore it into a second
# compose project with its own volumes, and prove it still answers.
#
#   scripts/dr-drill.sh [--keep] [--results docs/benchmarks/dr-drill.md]
#
#  1. Starts a throwaway source stack (scripts/e2e-stack.sh: production mode,
#     fresh strong secrets, deterministic mock LLM), bootstraps an admin,
#     uploads the e2e fixture and asks the golden question (the answer must
#     cite the fixture).
#  2. scripts/backup.sh → timed (the backup window).
#  3. Stops the source stack (its volumes stay until the end) — the "disaster".
#  4. scripts/restore.sh --yes into project raggie-drill-dst (fresh volumes,
#     same configuration), then starts it — timed from here: the RTO.
#  5. Checks the schema version and the document/user counts against the
#     manifest, signs in again and asks the golden question once more.
#  6. Prints the timings and rewrites the results block of --results.
# Needs Docker, ~8 GB RAM and a few GB of disk; it is meant for CI
# (.github/workflows/dr-drill.yml). Both projects are removed with their
# volumes at the end unless --keep; on failure DR_DRILL_LOGS=<dir> receives
# their logs.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/.." && pwd)"
# shellcheck source=../deploy/scripts/lib.sh
. "$REPO_ROOT/deploy/scripts/lib.sh"

SRC=raggie-drill-src
DST=raggie-drill-dst
FIXTURE="$REPO_ROOT/web/e2e/stack/fixtures/raggie-e2e-handbook.pdf"
QUESTION="How many days of annual leave do employees get?"
MARK_START="<!-- dr-drill:results:start -->"
MARK_END="<!-- dr-drill:results:end -->"

usage() { awk 'NR > 3 && /^#/ { sub(/^# ?/, ""); print; next } NR > 3 { exit }' "$0"; }
json() { python3 -c 'import json,sys; v=json.load(sys.stdin)
for k in sys.argv[1].split("."): v=v[int(k)] if isinstance(v,list) else v[k]
print(v)' "$1"; }
now() { date +%s; }
dst_sql() { "$W/compose-dst" exec -T postgres psql -U raggie -d raggie -tAc "$1" | tr -d '[:space:]'; }

# write_compose NAME PROJECT: a .raggie/compose-style wrapper for one project,
# on the e2e stack's generated files.
write_compose() {
  local q
  printf -v q '%q ' docker compose -p "$2" -f "$REPO_ROOT/deploy/compose/docker-compose.yml" \
    -f "$STACK/compose.override.yml" --env-file "$STACK/compose.env" --profile core --profile mock
  printf '#!/usr/bin/env bash\nexec %s"$@"\n' "$q" >"$W/$1"
  chmod 755 "$W/$1"
}

wait_ready() { # URL TIMEOUT
  local deadline=$(($(now) + $2))
  until curl -fsS -m 5 -o /dev/null "$1"; do
    (($(now) < deadline)) || r_die "$1 did not become ready"
    sleep 3
  done
}

login() { # → access token
  curl -fsS -m 30 -X POST "$CP/api/v1/auth/login" -H 'content-type: application/json' \
    --data-binary @- <<EOF | json access_token
{"email": "$ADMIN_EMAIL", "password": "$ADMIN_PASSWORD"}
EOF
}

# ask TOKEN → 0 when the streamed answer cites the fixture
ask() {
  local out="$W/answer-$RANDOM.sse"
  curl -fsS -N -m 180 -X POST "$EDGE/api/v1/chat/stream" \
    -H "Authorization: Bearer $1" -H 'content-type: application/json' \
    --data-binary "{\"workspace_id\": \"$WORKSPACE_ID\", \"message\": \"$QUESTION\"}" >"$out" || true
  grep -q '^event: sources' "$out" && grep -q "$(basename "$FIXTURE")" "$out" && grep -q '\[1\]' "$out"
}

seed() {
  local token
  ADMIN_EMAIL="drill-admin@raggie.example"
  ADMIN_PASSWORD="Drill-$(openssl rand -hex 12)"
  token="$(curl -fsS -m 30 -X POST "$CP/api/v1/onboarding/bootstrap" -H 'content-type: application/json' \
    --data-binary @- <<EOF | json access_token
{"email": "$ADMIN_EMAIL", "password": "$ADMIN_PASSWORD", "org_name": "DR drill", "setup_token": "$E2E_SETUP_TOKEN"}
EOF
)"
  WORKSPACE_ID="$(curl -fsS -m 30 -X POST "$CP/api/v1/onboarding/workspace" \
    -H "Authorization: Bearer $token" -H 'content-type: application/json' \
    --data-binary '{"type": "INTERNAL", "name": "DR drill"}' | json workspace.id)"
  curl -fsS -m 120 -X POST "$CP/api/v1/admin/workspaces/$WORKSPACE_ID/documents" \
    -H "Authorization: Bearer $token" -F "file=@$FIXTURE;type=application/pdf" >/dev/null
  local deadline=$(($(now) + 900)) status=""
  while [[ "$status" != SUCCESS ]]; do
    (($(now) < deadline)) || r_die "the fixture did not finish ingesting (status: ${status:-none})"
    sleep 5
    status="$(curl -fsS -m 30 -H "Authorization: Bearer $token" \
      "$CP/api/v1/admin/workspaces/$WORKSPACE_ID/documents" | json 0.status)"
    [[ "$status" != FAILED ]] || r_die "the fixture failed to ingest"
  done
  ask "$token" || r_die "golden question on the source stack: no cited answer"
}

write_results() { # FILE: rewrite the block between the markers
  local file=$1 block="$W/results.md"
  {
    echo "$MARK_START"
    echo "| | |"
    echo "|---|---|"
    echo "| Date (UTC) | $(date -u +%Y-%m-%dT%H:%MZ) |"
    echo "| Revision | \`$(git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)\` |"
    echo "| Runner | $(uname -sm), $(getconf _NPROCESSORS_ONLN 2>/dev/null || echo ?) CPU |"
    echo "| Backup duration (backup window) | ${BACKUP_SECONDS}s |"
    echo "| Backup size | $(du -sh "$BACKUP" | awk '{print $1}') |"
    echo "| Restore (verify + datastores + pg/Qdrant/files) | ${RESTORE_SECONDS}s |"
    echo "| RTO (restore start → cited answer) | ${RTO_SECONDS}s |"
    echo "| RPO | the backup interval + ${BACKUP_SECONDS}s (writes after the backup started are not in it) |"
    echo "| Schema / documents / users | ${SCHEMA} / ${DOCS} / ${USERS} (match the manifest) |"
    echo "| Result | **${RESULT}** |"
    echo "$MARK_END"
  } >"$block"
  if [[ -f "$file" ]] && grep -qF "$MARK_START" "$file"; then
    python3 - "$file" "$block" "$MARK_START" "$MARK_END" <<'PY'
import sys
path, block, start, end = sys.argv[1:]
text = open(path, encoding="utf-8").read()
head, rest = text.split(start, 1)
_, tail = rest.split(end, 1)
open(path, "w", encoding="utf-8").write(head + open(block, encoding="utf-8").read().rstrip("\n") + tail)
PY
  else
    cat "$block" >>"$file"
  fi
  r_log "results written to $file"
}

cleanup() {
  # A failed drill still leaves its record (RESULT=FAIL and the timings so far).
  [[ "$RESULT" == PASS ]] || write_results "$RESULTS_FILE" || true
  if [[ "$RESULT" != PASS && -n "${DR_DRILL_LOGS:-}" ]]; then # CI uploads these
    mkdir -p "$DR_DRILL_LOGS"
    local w
    for w in compose-src compose-dst; do
      [[ -x "$W/$w" ]] && "$W/$w" logs --no-color --tail 300 >"$DR_DRILL_LOGS/$w.log" 2>&1 || true
    done
  fi
  [[ "${KEEP:-0}" -eq 1 ]] && { r_log "kept both projects and $W (--keep)"; return; }
  [[ -x "$W/compose-dst" ]] && "$W/compose-dst" down -v --remove-orphans >/dev/null 2>&1 || true
  RAGGIE_E2E_PROJECT=$SRC RAGGIE_E2E_DIR="$STACK" "$REPO_ROOT/scripts/e2e-stack.sh" down >/dev/null 2>&1 || true
  rm -rf "$W"
}

main() {
  RESULTS_FILE="$REPO_ROOT/docs/benchmarks/dr-drill.md"
  KEEP=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --keep) KEEP=1 && shift ;;
      --results) RESULTS_FILE=$2 && shift 2 ;;
      -h | --help) usage && return 0 ;;
      *) r_die "unknown option: $1" ;;
    esac
  done
  for tool in docker curl python3 openssl; do command -v "$tool" >/dev/null || r_die "$tool is required"; done
  W="$(mktemp -d)"
  STACK="$W/stack"
  RESULT=FAIL BACKUP_SECONDS=0 RESTORE_SECONDS=0 RTO_SECONDS=0 SCHEMA="?" DOCS="?" USERS="?" BACKUP="$W"
  trap cleanup EXIT

  r_log "1/6 source stack ($SRC)"
  eval "$(RAGGIE_E2E_PROJECT=$SRC RAGGIE_E2E_DIR="$STACK" "$REPO_ROOT/scripts/e2e-stack.sh" up)"
  CP="$E2E_CONTROL_PLANE_URL" EDGE="$E2E_EDGE_URL"
  write_compose compose-src "$SRC"
  write_compose compose-dst "$DST"
  seed

  r_log "2/6 backup"
  local t0
  t0=$(now)
  BACKUP="$(cd "$W" && "$REPO_ROOT/scripts/backup.sh" --compose "$W/compose-src" \
    --env-file "$STACK/compose.env" --out "$W/backups" | tail -n1)"
  BACKUP_SECONDS=$(($(now) - t0))

  r_log "3/6 disaster: stopping $SRC"
  "$W/compose-src" down >/dev/null

  r_log "4/6 restore into $DST"
  t0=$(now)
  (cd "$W" && "$REPO_ROOT/scripts/restore.sh" "$BACKUP" --yes --compose "$W/compose-dst" \
    --env-file "$STACK/compose.env")
  RESTORE_SECONDS=$(($(now) - t0))
  "$W/compose-dst" up -d --wait >/dev/null
  wait_ready "$CP/readyz" 300

  r_log "5/6 checks"
  SCHEMA="$(dst_sql "SELECT max(version) FROM schema_migrations")"
  DOCS="$(dst_sql "SELECT count(*) FROM documents WHERE deleted_at IS NULL")"
  USERS="$(dst_sql "SELECT count(*) FROM users")"
  local want_schema want_docs want_users
  want_schema="$(python3 "$REPO_ROOT/scripts/lib/backup_manifest.py" get "$BACKUP" schema_version)"
  want_docs="$(python3 "$REPO_ROOT/scripts/lib/backup_manifest.py" get "$BACKUP" counts.documents)"
  want_users="$(python3 "$REPO_ROOT/scripts/lib/backup_manifest.py" get "$BACKUP" counts.users)"
  [[ "$SCHEMA" == "$want_schema" && "$DOCS" == "$want_docs" && "$USERS" == "$want_users" ]] ||
    r_die "restored $SCHEMA/$DOCS/$USERS, manifest says $want_schema/$want_docs/$want_users"
  local deadline=$(($(now) + 300))
  until ask "$(login)"; do
    (($(now) < deadline)) || r_die "golden question on the restored stack: no cited answer"
    sleep 5
  done
  RTO_SECONDS=$(($(now) - t0))
  RESULT=PASS

  r_log "6/6 backup ${BACKUP_SECONDS}s, restore ${RESTORE_SECONDS}s, RTO ${RTO_SECONDS}s"
  write_results "$RESULTS_FILE"
}

main "$@"
