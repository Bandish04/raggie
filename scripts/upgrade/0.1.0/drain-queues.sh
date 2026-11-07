#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# shellcheck source-path=SCRIPTDIR
# Drain the Redis event streams before switching to Valkey (0.1.0 starts it on
# a fresh volume, so anything still queued would be lost).
#
#   scripts/upgrade/0.1.0/drain-queues.sh [--dir <install dir>] [--env-file <path>]
#       [--timeout 1800] [--interval 5] [--skip-eval] [--keep-producers] [--dry-run]
#
# 1. Stops the producers (caddy, web, edge, control-plane, scheduler-worker) so
#    no new uploads, chats or retries arrive. --keep-producers skips this when
#    the install is already in maintenance some other way.
# 2. Waits, with the ingestion and eval workers still running, until every
#    consumer group has nothing pending and nothing undelivered.
#    --skip-eval does not wait for eval-workers (in-flight answers then simply
#    get no faithfulness score).
# 3. Stops ingestion-worker and eval-worker, and reports documents still
#    PENDING/PROCESSING in Postgres (the stale-document sweep re-runs them
#    after the upgrade).
# Exits 1 on timeout, leaving the workers running so you can wait longer.
# --dry-run only reports the backlog. Containers are found by compose labels,
# so this works with the pre-0.1.0 compose file still in place.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$HERE/lib.sh"

PRODUCERS=(caddy web edge control-plane scheduler-worker)
CONSUMERS=(ingestion-worker eval-worker)

stop_services() {
  local svc cid
  for svc in "$@"; do
    cid="$(compose_container "$svc")"
    if [[ -n "$cid" ]]; then
      log "stopping $svc"
      docker stop "$cid" >/dev/null
    fi
  done
}

# backlog_report ENV_FILE SKIP_EVAL: one "stream group backlog" line per group;
# returns 0 when everything waited for is drained.
backlog_report() {
  local env_file=$1 skip_eval=$2 pair stream group backlog drained=0
  for pair in "${STREAM_GROUPS[@]}"; do
    read -r stream group <<<"$pair"
    [[ "$skip_eval" == 1 && "$group" == eval-workers ]] && continue
    backlog="$(stream_backlog "$env_file" "$stream" "$group")"
    printf '  %-28s %-18s %s\n' "$stream" "$group" "$backlog" >&2
    [[ "$backlog" == 0 ]] || drained=1
  done
  return $drained
}

pending_documents() {
  local env_file=$1 cid user db
  cid="$(compose_container postgres)"
  [[ -n "$cid" ]] || return 0
  user="$(env_get "$env_file" POSTGRES_USER)"
  db="$(env_get "$env_file" POSTGRES_DB)"
  docker exec "$cid" psql -U "${user:-raggie}" -d "${db:-raggie}" -tA -F ' ' -c \
    "SELECT status, count(*) FROM documents WHERE deleted_at IS NULL AND archived_at IS NULL
       AND status IN ('PENDING', 'PROCESSING') GROUP BY status" 2>/dev/null
}

main() {
  local dir="." env_file="" timeout=1800 interval=5 skip_eval=0 keep_producers=0 dry_run=0
  local deadline svc
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --dir) dir=$2 && shift 2 ;;
      --env-file) env_file=$2 && shift 2 ;;
      --timeout) timeout=$2 && shift 2 ;;
      --interval) interval=$2 && shift 2 ;;
      --skip-eval) skip_eval=1 && shift ;;
      --keep-producers) keep_producers=1 && shift ;;
      --dry-run) dry_run=1 && shift ;;
      -h | --help) usage && return 0 ;;
      *) die "unknown option: $1" ;;
    esac
  done
  env_file="${env_file:-$dir/.env}"
  [[ -f "$env_file" ]] || die "no .env at $env_file (use --dir or --env-file)"
  command -v docker >/dev/null || die "docker not found"
  [[ -n "$(compose_container redis)" ]] || die "the $UPGRADE_PROJECT redis container is not running"

  log "current backlog (stream, group, entries pending + undelivered):"
  if backlog_report "$env_file" "$skip_eval"; then
    log "already drained"
  fi
  if [[ $dry_run -eq 1 ]]; then
    return 0
  fi
  for svc in ingestion-worker $([[ $skip_eval == 1 ]] || echo eval-worker); do
    [[ -n "$(compose_container "$svc")" ]] ||
      die "$svc is not running: nothing would drain its stream (start it, or use --skip-eval for eval-worker)"
  done

  [[ $keep_producers -eq 1 ]] || stop_services "${PRODUCERS[@]}"

  deadline=$(($(date +%s) + timeout))
  until backlog_report "$env_file" "$skip_eval"; do
    if (($(date +%s) >= deadline)); then
      log "timed out after ${timeout}s; the workers keep running — re-run to wait longer"
      return 1
    fi
    sleep "$interval"
  done
  log "all consumer groups drained"

  stop_services "${CONSUMERS[@]}"
  local docs
  docs="$(pending_documents "$env_file")"
  if [[ -n "$docs" ]]; then
    log "documents still PENDING/PROCESSING in Postgres (re-run by the stale sweep after the upgrade):"
    printf '  %s\n' "$docs" >&2
  else
    log "no document is PENDING/PROCESSING"
  fi
  log "drained; safe to stop the stack and switch to Valkey"
}

if [[ -z "${UPGRADE_LIB_ONLY:-}" ]]; then
  main "$@"
fi
