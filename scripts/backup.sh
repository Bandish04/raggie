#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# shellcheck source-path=SCRIPTDIR
# Back up a Docker Compose install of Raggie. Run it from the install directory
# (where .env lives); it uses .raggie/compose when present.
#
#   scripts/backup.sh [--out DIR] [--objects-dest local|s3:BUCKET[/PREFIX]]
#       [--include-env] [--retention N] [--skip-qdrant] [--skip-objects]
#       [--env-file PATH] [--compose PATH]
#
# Writes DIR/raggie-backup-<UTC timestamp>/ (mode 700, default DIR
# ~/raggie-backups, outside the install directory) with:
#   postgres.dump        pg_dump -Fc of the database
#   qdrant/<c>.snapshot  a snapshot of every Qdrant collection (the API key is
#                        sent as a header from a 0600 file)
#   objects/             the uploaded files, copied with a pinned rclone image;
#                        objects.sha256 lists every file's sha256. With
#                        --objects-dest s3:BUCKET/PREFIX they go to that S3
#                        target instead (BACKUP_S3_ENDPOINT, BACKUP_S3_ACCESS_KEY_ID,
#                        BACKUP_S3_SECRET_ACCESS_KEY, optional BACKUP_S3_REGION /
#                        BACKUP_S3_PROVIDER).
#   env/                 only with --include-env: .env and .env.embeddings
#                        (SECRETS — encrypt the backup), mode 600
#   manifest.json        version, schema version, embeddings fingerprint,
#                        collections, counts and the sha256 of every artifact
# The datastores must be running; the app may keep serving (pg_dump is
# consistent, Qdrant snapshots are per collection). Nothing at the source is
# ever deleted: rclone only copies, and the only Qdrant call that deletes
# removes the snapshot this run just downloaded. --retention N keeps the N
# newest backups in DIR, counting this one (only real directories named like
# the ones this script writes and holding a manifest.json; never this one).
# Everything is written with umask 077; DIR must be owned by the current user.
# With BACKUP_MANIFEST_KEY set, manifest.json is signed (manifest.json.hmac).
set -euo pipefail
umask 077

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/backup-common.sh
. "$HERE/lib/backup-common.sh"

usage() { awk 'NR > 3 && /^#/ { sub(/^# ?/, ""); print; next } NR > 3 { exit }' "$0"; }

BK_BACKUP_NAME_RE='^raggie-backup-[0-9]{8}T[0-9]{6}Z(-[0-9]{1,2})?$'

# prune_backups DIR N CURRENT: keep the N newest backups in DIR, CURRENT (the
# one just written) included and never removed. Only real directories (no
# symlinks) directly in DIR, named like the ones this script writes and holding
# a manifest.json, are candidates; anything else in DIR is left alone.
prune_backups() {
  local dir=$1 keep=$2 current=$3 d base n=1
  while IFS= read -r -d '' d; do
    base="${d##*/}"
    [[ "$base" =~ $BK_BACKUP_NAME_RE ]] || continue
    [[ "$d" == "$dir/$base" && "$d" != "$current" && ! -L "$d" && -d "$d" && -f "$d/manifest.json" ]] || continue
    n=$((n + 1))
    if ((n > keep)); then
      r_log "retention: removing $base"
      rm -rf -- "$d"
    fi
  done < <(find "$dir" -mindepth 1 -maxdepth 1 -type d -name 'raggie-backup-*' -print0 | sort -rz)
}

main() {
  local out="${RAGGIE_BACKUP_DIR:-$HOME/raggie-backups}" objects_dest=local include_env=0
  local retention=0 skip_qdrant=0 skip_objects=0 env_file=".env" compose=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --out) out=$2 && shift 2 ;;
      --objects-dest) objects_dest=$2 && shift 2 ;;
      --include-env) include_env=1 && shift ;;
      --retention) retention=$2 && shift 2 ;;
      --skip-qdrant) skip_qdrant=1 && shift ;;
      --skip-objects) skip_objects=1 && shift ;;
      --env-file) env_file=$2 && shift 2 ;;
      --compose) compose=$2 && shift 2 ;;
      -h | --help) usage && return 0 ;;
      *) r_die "unknown option: $1 (see --help)" ;;
    esac
  done
  [[ "$retention" =~ ^[0-9]+$ ]] || r_die "--retention takes a number"
  [[ "$objects_dest" == local || "$objects_dest" == s3:?* ]] ||
    r_die "--objects-dest is local or s3:BUCKET[/PREFIX]"
  command -v python3 >/dev/null || r_die "python3 is required"
  bk_init "$env_file" "$compose"
  bk_require_running postgres
  [[ $skip_qdrant -eq 1 ]] || bk_require_running qdrant
  [[ $skip_objects -eq 1 ]] || bk_require_running objectstore

  local started name b i=1
  started=$(date +%s)
  name="raggie-backup-$(date -u +%Y%m%dT%H%M%SZ)"
  mkdir -p "$out"
  out="$(cd "$out" && pwd -P)"
  [[ -O "$out" ]] || r_die "$out is not owned by $(id -un); choose a backup directory you own"
  while ! (umask 077 && mkdir "$out/$name" 2>/dev/null); do # two runs in one second
    i=$((i + 1))
    ((i < 100)) || r_die "cannot create a backup directory in $out"
    name="raggie-backup-$(date -u +%Y%m%dT%H%M%SZ)-$i"
  done
  b="$out/$name"
  chmod 700 "$b"
  r_log "backing up into $b"

  # ── PostgreSQL ──
  bk_compose exec -T postgres pg_dump -U "$(bk_pg_user)" -d "$(bk_pg_db)" -Fc >"$b/postgres.dump"
  [[ -s "$b/postgres.dump" ]] || r_die "pg_dump produced nothing"
  local schema fp collection docs indexed users workspaces
  schema="$(bk_sql "SELECT max(version) FROM schema_migrations")"
  [[ -n "$schema" ]] || r_die "cannot read the schema version"
  fp="$(bk_sql "SELECT coalesce(embedding_fingerprint, '') FROM system_settings WHERE id = 'current'")"
  collection="$(bk_sql "SELECT coalesce(embedding_profile->>'collection', '') FROM system_settings WHERE id = 'current'")"
  docs="$(bk_sql "SELECT count(*) FROM documents WHERE deleted_at IS NULL")"
  indexed="$(bk_sql "SELECT count(*) FROM documents WHERE deleted_at IS NULL AND status IN ('SUCCESS', 'READY')")"
  users="$(bk_sql "SELECT count(*) FROM users")"
  workspaces="$(bk_sql "SELECT count(*) FROM workspaces")"
  bk_require_number "document count" "$docs"
  bk_require_number "indexed document count" "$indexed"
  bk_require_number "user count" "$users"
  bk_require_number "workspace count" "$workspaces"
  [[ -n "$fp" ]] || r_warn "no embedding fingerprint recorded: a restore of this backup needs --allow-no-fingerprint"
  r_log "postgres: schema $schema, $docs live document(s)"

  # ── Qdrant ──
  local qdrant_json="[]" collections c resp snap points
  if [[ $skip_qdrant -eq 0 ]]; then
    mkdir -p "$b/qdrant"
    qdrant_json=""
    collections="$(bk_qdrant_collections)" || exit 1
    if [[ "$indexed" != 0 && -z "$collections" ]]; then
      r_die "found no Qdrant collection, but $indexed document(s) are indexed: is this the right Qdrant ($(bk_qdrant_url))? (--skip-qdrant backs up without vectors)"
    fi
    if [[ "$indexed" != 0 && -n "$collection" && $'\n'"$collections"$'\n' != *$'\n'"$collection"$'\n'* ]]; then
      r_die "the active collection $collection is not in Qdrant, but $indexed document(s) are indexed"
    fi
    for c in $collections; do
      resp="$(bk_qdrant POST "collections/$c/snapshots?wait=true")" || r_die "Qdrant did not create a snapshot of $c"
      snap="$(printf '%s' "$resp" | bk_json_get result.name)"
      [[ "$snap" =~ $BK_SNAPSHOT_RE ]] || r_die "unexpected snapshot name from Qdrant for $c: '$snap'"
      bk_qdrant GET "collections/$c/snapshots/$snap" -o "$b/qdrant/$c.snapshot"
      bk_qdrant DELETE "collections/$c/snapshots/$snap" >/dev/null # the copy just taken, not data
      resp="$(bk_qdrant GET "collections/$c")" || r_die "cannot read collection $c"
      points="$(printf '%s' "$resp" | bk_json_get result.points_count)"
      bk_require_number "point count of $c" "$points"
      qdrant_json+="${qdrant_json:+,}{\"collection\":\"$c\",\"points\":$points,\"file\":\"qdrant/$c.snapshot\"}"
      r_log "qdrant: $c ($points points)"
    done
    qdrant_json="[$qdrant_json]"
  fi

  # ── Object store ──
  local bucket location="" src_count=0 src_bytes=0 dst_count size
  if [[ $skip_objects -eq 0 ]]; then
    bucket="$(bk_env MINIO_BUCKET)"
    bucket="${bucket:-raggie-uploads}"
    bk_store_env
    bk_find_network
    size="$(bk_rclone_size "store:$bucket")" || exit 1
    read -r src_count src_bytes <<<"$size"
    if [[ "$objects_dest" == local ]]; then
      BK_RCLONE_MOUNTS=("$b:/backup")
      bk_rclone copy --transfers 4 --checkers 8 "store:$bucket" /backup/objects
      size="$(bk_rclone_size /backup/objects)" || exit 1
      read -r dst_count _ <<<"$size"
      location=objects
      python3 "$BK_MANIFEST" hash-objects "$b"
    else
      [[ -n "${BACKUP_S3_ACCESS_KEY_ID:-}" ]] || r_die "--objects-dest s3:… needs BACKUP_S3_ACCESS_KEY_ID / BACKUP_S3_SECRET_ACCESS_KEY"
      bk_store_env
      location="s3:${objects_dest#s3:}/$name"
      bk_rclone copy --transfers 4 --checkers 8 "store:$bucket" "offsite:${objects_dest#s3:}/$name"
      size="$(bk_rclone_size "offsite:${objects_dest#s3:}/$name")" || exit 1
      read -r dst_count _ <<<"$size"
    fi
    ((dst_count >= src_count)) ||
      r_die "object copy incomplete: $dst_count of $src_count object(s); re-run the backup"
    r_log "objects: $src_count file(s), $src_bytes bytes → $location"
  fi

  # ── Configuration (opt-in) ──
  if [[ $include_env -eq 1 ]]; then
    printf '\n%s\n%s\n\n' \
      "!!! --include-env: this backup now contains SECRETS (JWT_SECRET, INTEGRATION_ENC_KEY," \
      "!!! database and object-store passwords). Encrypt it and restrict who can read it." >&2
    (umask 077 && mkdir -p "$b/env")
    local f
    for f in "$BK_ENV_FILE" "$(dirname "$BK_ENV_FILE")/.env.embeddings"; do
      [[ -f "$f" ]] || continue
      cp "$f" "$b/env/$(basename "$f")"
      chmod 600 "$b/env/$(basename "$f")"
    done
  fi

  python3 "$BK_MANIFEST" write "$b" \
    --str created_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --str raggie_version="$(bk_installed_version)" \
    --str schema_version="$schema" \
    --str embeddings.fingerprint="$fp" \
    --str embeddings.collection="$collection" \
    --num counts.documents="$docs" --num counts.users="$users" \
    --num counts.workspaces="$workspaces" \
    --json qdrant="$qdrant_json" \
    --str objects.location="$location" \
    --num objects.count="$src_count" --num objects.bytes="$src_bytes" \
    --json include_env="$([[ $include_env -eq 1 ]] && echo true || echo false)" \
    --num duration_seconds="$(($(date +%s) - started))"

  [[ $retention -eq 0 ]] || prune_backups "$out" "$retention" "$b"
  r_log "backup complete in $(($(date +%s) - started))s: $b"
  printf '%s\n' "$b"
}

main "$@"
