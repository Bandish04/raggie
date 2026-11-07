#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# shellcheck source-path=SCRIPTDIR
# Restore a backup written by scripts/backup.sh into a STOPPED Docker Compose
# install of Raggie. Run it from the install directory.
#
#   scripts/restore.sh BACKUP_DIR [--yes] [--reindex] [--allow-no-fingerprint]
#       [--skip-objects] [--env-file PATH] [--compose PATH]
#
# 1. Refuses a backup directory (or anything in it) that is group- or
#    world-writable, then verifies it against manifest.json: what it restores
#    must be listed, every listed file must match its sha256 (objects through
#    objects.sha256), and an unlisted file or a symlink fails. With
#    BACKUP_MANIFEST_KEY set the manifest's HMAC (manifest.json.hmac) must match.
# 2. Refuses while any application service (web, edge, control-plane, workers,
#    caddy) has a container that is not exited, and when the compose state
#    cannot be read: stop them first (`<compose> down`, never `down -v`).
# 3. Starts the datastores and the embeddings gateway, and refuses when the
#    gateway's embedding fingerprint differs from the backup's: the snapshots
#    would hold vectors of another model. --reindex restores without the Qdrant
#    snapshots instead and re-publishes every document, so the workers
#    re-embed them with the current model once the stack is started. A backup
#    without a fingerprint needs --allow-no-fingerprint (or --reindex).
# 4. After a typed confirmation (or --yes) it verifies the backup and the
#    stopped stack again, then overwrites: Postgres
#    (pg_restore --clean --if-exists), the Qdrant collections in the backup
#    (snapshot upload, priority=snapshot) and copies the files back into the
#    bucket (copy only: objects that are not in the backup are kept).
# Put the backed-up .env back yourself first if this is a new machine
# (env/.env when the backup was made with --include-env). Then start
# everything: `<compose> up -d`.
set -euo pipefail
umask 077

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/backup-common.sh
. "$HERE/lib/backup-common.sh"

usage() { awk 'NR > 3 && /^#/ { sub(/^# ?/, ""); print; next } NR > 3 { exit }' "$0"; }

# confirm_restore: --yes, or the word RESTORE typed on the terminal.
confirm_restore() {
  local tty="${RAGGIE_TTY:-/dev/tty}" answer=""
  if ! { : <"$tty"; } 2>/dev/null; then
    r_die "no terminal to confirm on; re-run with --yes to overwrite the data of this install"
  fi
  printf 'This OVERWRITES the database, the vectors and the files of this install.\nType RESTORE to continue: ' >&2
  IFS= read -r answer <"$tty" || true
  [[ "$answer" == RESTORE ]] || r_die "not confirmed; nothing was changed"
}

gateway_fingerprint() { # the embeddings gateway's active fingerprint (waits for it)
  local deadline info
  deadline=$(($(date +%s) + ${RESTORE_GATEWAY_WAIT:-600}))
  while :; do
    info="$(bk_compose exec -T embeddings python -c '
import os, urllib.request as u
r = u.Request("http://127.0.0.1:8002/v1/info")
s = os.environ.get("INTERNAL_API_SECRET")
if s:
    r.add_header("Authorization", "Bearer " + s)
print(u.urlopen(r, timeout=10).read().decode())' 2>/dev/null || true)"
    if [[ -n "$info" ]]; then
      printf '%s' "$info" | bk_json_get fingerprint
      return 0
    fi
    (($(date +%s) < deadline)) || r_die "the embeddings gateway did not answer /v1/info"
    sleep 5
  done
}

# require_stopped: no application service may be up (fails closed).
require_stopped() {
  local running
  running="$(bk_running_app_services)" || exit 1
  [[ -z "$running" ]] || r_die "application services are running ($running); stop them first (<compose> down, never -v)"
}

verify_backup() { # BACKUP
  local writable
  writable="$(find "$1" \( -type d -o -type f \) \( -perm -g+w -o -perm -o+w \) -print -quit)"
  [[ -z "$writable" ]] || r_die "$writable is group- or world-writable; fix the permissions (chmod -R go-w) before restoring"
  python3 "$BK_MANIFEST" verify "$1" || r_die "the backup does not match its manifest; refusing to restore it"
}

main() {
  local backup="" yes=0 reindex=0 allow_no_fp=0 skip_objects=0 env_file=".env" compose=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --yes) yes=1 && shift ;;
      --reindex) reindex=1 && shift ;;
      --allow-no-fingerprint) allow_no_fp=1 && shift ;;
      --skip-objects) skip_objects=1 && shift ;;
      --env-file) env_file=$2 && shift 2 ;;
      --compose) compose=$2 && shift 2 ;;
      -h | --help) usage && return 0 ;;
      -*) r_die "unknown option: $1 (see --help)" ;;
      *) backup=$1 && shift ;;
    esac
  done
  [[ -n "$backup" && -d "$backup" ]] || r_die "usage: scripts/restore.sh BACKUP_DIR [--yes] [--reindex]"
  backup="$(cd "$backup" && pwd -P)"
  command -v python3 >/dev/null || r_die "python3 is required"

  r_log "verifying $backup"
  verify_backup "$backup"

  bk_init "$env_file" "$compose"
  require_stopped

  local want have
  want="$(python3 "$BK_MANIFEST" get "$backup" embeddings.fingerprint)"
  if [[ -z "$want" && $reindex -eq 0 && $allow_no_fp -eq 0 ]]; then
    r_die "the backup records no embedding fingerprint, so its vectors cannot be matched to the gateway's model. Pass --allow-no-fingerprint to restore them as they are, or --reindex to rebuild them."
  fi
  r_log "starting the datastores and the embeddings gateway"
  bk_compose up -d --wait postgres redis qdrant objectstore embeddings
  have="$(gateway_fingerprint)"
  if [[ -n "$want" && "$want" != "$have" && $reindex -eq 0 ]]; then
    r_die "embedding fingerprint mismatch: the backup was indexed with $want, the gateway now runs $have. Configure the same embedding profile, or pass --reindex to rebuild the vectors with the current one."
  fi
  [[ -n "$want" ]] || r_warn "the backup records no embedding fingerprint; vectors are restored as they are"

  [[ $yes -eq 1 ]] || confirm_restore

  # Again, right before overwriting anything: the backup may have changed and
  # a service may have been started while we waited.
  r_log "verifying $backup again"
  verify_backup "$backup"
  [[ "$(python3 "$BK_MANIFEST" get "$backup" embeddings.fingerprint)" == "$want" ]] ||
    r_die "manifest.json changed during the restore; refusing to continue"
  require_stopped

  local collections
  collections="$(python3 "$BK_MANIFEST" collections "$backup")" || r_die "the manifest lists an unsafe collection name"

  r_log "restoring Postgres"
  bk_compose exec -T postgres pg_restore -U "$(bk_pg_user)" -d "$(bk_pg_db)" \
    --clean --if-exists --no-owner --exit-on-error <"$backup/postgres.dump"

  local c file
  if [[ $reindex -eq 0 ]]; then
    for c in $collections; do
      [[ "$c" =~ $BK_COLLECTION_RE ]] || r_die "unsafe collection name in the manifest: $c"
      file="$backup/qdrant/$c.snapshot"
      [[ -f "$file" ]] || r_die "missing snapshot $file"
      r_log "restoring Qdrant collection $c"
      bk_qdrant POST "collections/$c/snapshots/upload?priority=snapshot&wait=true" \
        -F "snapshot=@$file" >/dev/null
    done
  else
    r_log "--reindex: skipping the Qdrant snapshots"
  fi

  local location bucket
  location="$(python3 "$BK_MANIFEST" get "$backup" objects.location)"
  if [[ $skip_objects -eq 0 && -n "$location" ]]; then
    bucket="$(bk_env MINIO_BUCKET)"
    bucket="${bucket:-raggie-uploads}"
    bk_store_env
    bk_find_network
    bk_rclone mkdir "store:$bucket"
    if [[ "$location" == objects ]]; then
      BK_RCLONE_MOUNTS=("$backup:/backup:ro")
      bk_rclone copy --transfers 4 --checkers 8 /backup/objects "store:$bucket"
    else
      [[ -n "${BACKUP_S3_ACCESS_KEY_ID:-}" ]] || r_die "objects are at $location: set BACKUP_S3_* to read them"
      bk_store_env
      bk_rclone copy --transfers 4 --checkers 8 "offsite:${location#s3:}" "store:$bucket"
    fi
    r_log "files copied into $bucket"
  fi

  if [[ $reindex -eq 1 ]]; then
    r_log "re-publishing every document for re-embedding"
    bk_compose run --rm --no-deps control-plane python -m raggie_control_plane.reindex
  fi

  r_log "restore complete. Start the stack: ${BK_COMPOSE[*]} up -d"
  r_log "then sign in, open a known document and ask a question that cites it"
}

main "$@"
