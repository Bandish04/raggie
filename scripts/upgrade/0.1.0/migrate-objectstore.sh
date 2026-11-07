#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# shellcheck source-path=SCRIPTDIR
# Copy the uploaded files from the pre-0.1.0 MinIO volume into the 0.1.0
# SeaweedFS object store, then verify the copy.
#
#   scripts/upgrade/0.1.0/migrate-objectstore.sh [--dir <install dir>] [--env-file <path>]
#       [--dry-run] [--checksum-sample 25] [--bucket <name>] [--source-volume <volume>]
#       [--legacy-image <image>] [--rclone-image <image>] [--keep-legacy]
#
# Run it after the old stack is down and the new datastores are up
# (`up -d postgres redis qdrant objectstore`), BEFORE the application
# services start. It
#   1. starts a temporary MinIO (the image already cached on this host) on the
#      old `<project>_minio_data` volume, reachable only on the compose network;
#   2. `rclone copy`s the bucket into the new `objectstore` (never deletes,
#      skips objects already copied, so re-running is safe);
#   3. verifies object count + total size, that every source object exists on
#      the target with the same size, and the content of a random sample
#      (--checksum-sample N, 0 = off) by downloading both sides;
#   4. removes the temporary MinIO (unless --keep-legacy). Volumes are never
#      deleted.
# --dry-run lists what would be copied and changes nothing on the target.
# Credentials come from .env (MINIO_ROOT_USER / MINIO_ROOT_PASSWORD; override
# the legacy side with LEGACY_MINIO_ROOT_USER / LEGACY_MINIO_ROOT_PASSWORD) and
# reach the containers as environment variables, never on a command line.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$HERE/lib.sh"

RCLONE_IMAGE_DEFAULT="rclone/rclone:1.75.2@sha256:2687085f718d3c628f7fdfb77c52a1d344332aed543110bb88088f2c70d43eb5"
LEGACY_NAME="${UPGRADE_PROJECT}-minio-legacy-upgrade"
LEGACY_ALIAS="minio-legacy"

# parse_rclone_size < `rclone size --json` → "<count> <bytes>"
parse_rclone_size() {
  local json count bytes
  json="$(cat)"
  count="$(printf '%s' "$json" | grep -oE '"count":[0-9]+' | cut -d: -f2)"
  bytes="$(printf '%s' "$json" | grep -oE '"bytes":[0-9]+' | cut -d: -f2)"
  printf '%s %s' "${count:-0}" "${bytes:-0}"
}

# legacy_image: the image the old minio container ran, else a cached
# minio/minio:latest. Never pulls (upstream stopped publishing images).
legacy_image() {
  local cid image
  if [[ -n "${LEGACY_IMAGE:-}" ]]; then
    printf '%s' "$LEGACY_IMAGE"
    return
  fi
  cid="$(compose_container minio all)"
  [[ -n "$cid" ]] && image="$(docker inspect -f '{{.Image}}' "$cid" 2>/dev/null)"
  printf '%s' "${image:-minio/minio:latest}"
}

containers_on_volume() { # running containers that mount volume $1
  docker ps -q --filter "volume=$1"
}

rclone_run() {
  docker run --rm --network "$NETWORK" \
    -e RCLONE_CONFIG_LEGACY_TYPE -e RCLONE_CONFIG_LEGACY_PROVIDER -e RCLONE_CONFIG_LEGACY_ENDPOINT \
    -e RCLONE_CONFIG_LEGACY_ACCESS_KEY_ID -e RCLONE_CONFIG_LEGACY_SECRET_ACCESS_KEY \
    -e RCLONE_CONFIG_TARGET_TYPE -e RCLONE_CONFIG_TARGET_PROVIDER -e RCLONE_CONFIG_TARGET_ENDPOINT \
    -e RCLONE_CONFIG_TARGET_ACCESS_KEY_ID -e RCLONE_CONFIG_TARGET_SECRET_ACCESS_KEY \
    -v "$WORK:/work" "$RCLONE_IMAGE" "$@"
}

cleanup() {
  [[ -n "${WORK:-}" ]] && rm -rf "$WORK"
  if [[ "${KEEP_LEGACY:-0}" -eq 0 && -n "${STARTED_LEGACY:-}" ]]; then
    docker rm -f "$LEGACY_NAME" >/dev/null 2>&1 && log "removed the temporary MinIO"
  fi
}

main() {
  local dir="." env_file="" dry_run=0 sample=25 bucket="" volume="" image target_cid
  RCLONE_IMAGE="$RCLONE_IMAGE_DEFAULT"
  KEEP_LEGACY=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --dir) dir=$2 && shift 2 ;;
      --env-file) env_file=$2 && shift 2 ;;
      --dry-run) dry_run=1 && shift ;;
      --checksum-sample) sample=$2 && shift 2 ;;
      --bucket) bucket=$2 && shift 2 ;;
      --source-volume) volume=$2 && shift 2 ;;
      --legacy-image) LEGACY_IMAGE=$2 && shift 2 ;;
      --rclone-image) RCLONE_IMAGE=$2 && shift 2 ;;
      --keep-legacy) KEEP_LEGACY=1 && shift ;;
      -h | --help) usage && return 0 ;;
      *) die "unknown option: $1" ;;
    esac
  done
  env_file="${env_file:-$dir/.env}"
  [[ -f "$env_file" ]] || die "no .env at $env_file (use --dir or --env-file)"
  command -v docker >/dev/null || die "docker not found"
  volume="${volume:-${UPGRADE_PROJECT}_minio_data}"
  bucket="${bucket:-$(env_get "$env_file" MINIO_BUCKET)}"
  bucket="${bucket:-raggie-uploads}"

  docker volume inspect "$volume" >/dev/null 2>&1 || die "volume $volume not found: nothing to migrate"
  target_cid="$(compose_container objectstore)"
  [[ -n "$target_cid" ]] ||
    die "the new objectstore is not running: start the datastores first (up -d postgres redis qdrant objectstore)"
  NETWORK="$(docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}' "$target_cid" | awk '{print $1}')"
  image="$(legacy_image)"
  docker image inspect "$image" >/dev/null 2>&1 ||
    die "MinIO image $image is not cached on this host; pass --legacy-image (it is not pulled automatically)"

  local user pass luser lpass
  user="$(env_get "$env_file" MINIO_ROOT_USER)"
  pass="$(env_get "$env_file" MINIO_ROOT_PASSWORD)"
  luser="${LEGACY_MINIO_ROOT_USER:-$user}"
  lpass="${LEGACY_MINIO_ROOT_PASSWORD:-$pass}"
  [[ -n "$user" && -n "$pass" ]] || die "MINIO_ROOT_USER / MINIO_ROOT_PASSWORD missing from $env_file"
  export RCLONE_CONFIG_LEGACY_TYPE=s3 RCLONE_CONFIG_LEGACY_PROVIDER=Minio \
    RCLONE_CONFIG_LEGACY_ENDPOINT="http://$LEGACY_ALIAS:9000" \
    RCLONE_CONFIG_LEGACY_ACCESS_KEY_ID="$luser" RCLONE_CONFIG_LEGACY_SECRET_ACCESS_KEY="$lpass" \
    RCLONE_CONFIG_TARGET_TYPE=s3 RCLONE_CONFIG_TARGET_PROVIDER=SeaweedFS \
    RCLONE_CONFIG_TARGET_ENDPOINT="http://objectstore:9000" \
    RCLONE_CONFIG_TARGET_ACCESS_KEY_ID="$user" RCLONE_CONFIG_TARGET_SECRET_ACCESS_KEY="$pass"

  WORK="$(mktemp -d)"
  chmod 755 "$WORK"
  trap cleanup EXIT

  # Two MinIO servers on one volume would corrupt it: only ours may run.
  local holders
  holders="$(containers_on_volume "$volume")"
  if [[ -n "$holders" ]]; then
    if [[ "$holders" == "$(docker ps -q --filter "name=^${LEGACY_NAME}$")" ]]; then
      log "reusing the running temporary MinIO"
    else
      die "a running container uses $volume; stop the old stack first (docker compose down, never -v)"
    fi
  else
    docker rm -f "$LEGACY_NAME" >/dev/null 2>&1 # a leftover from an interrupted run
    log "starting a temporary MinIO ($image) on $volume"
    MINIO_ROOT_USER="$luser" MINIO_ROOT_PASSWORD="$lpass" docker run -d --name "$LEGACY_NAME" \
      --network "$NETWORK" --network-alias "$LEGACY_ALIAS" \
      -e MINIO_ROOT_USER -e MINIO_ROOT_PASSWORD -v "$volume:/data" "$image" server /data >/dev/null ||
      die "could not start the temporary MinIO"
    STARTED_LEGACY=1
  fi
  local i
  for i in $(seq 1 30); do
    rclone_run lsd legacy: >/dev/null 2>&1 && break
    [[ $i -eq 30 ]] && die "the temporary MinIO did not answer (wrong credentials? see: docker logs $LEGACY_NAME)"
    sleep 2
  done

  local src src_count src_bytes
  if ! src="$(rclone_run size --json "legacy:$bucket" 2>/dev/null | parse_rclone_size)"; then
    die "cannot list legacy:$bucket"
  fi
  read -r src_count src_bytes <<<"$src"
  log "source legacy:$bucket — $src_count object(s), $src_bytes bytes"
  if [[ "$src_count" -eq 0 ]]; then
    log "nothing to copy"
    return 0
  fi

  if [[ $dry_run -eq 1 ]]; then
    rclone_run copy --dry-run --checkers 8 "legacy:$bucket" "target:$bucket" 2>&1 | tail -n 20 >&2
    log "dry run: nothing was written"
    return 0
  fi

  rclone_run mkdir "target:$bucket" || die "cannot create target:$bucket"
  log "copying (re-runs skip what is already there)"
  rclone_run copy --transfers 4 --checkers 8 --stats 30s --stats-one-line \
    "legacy:$bucket" "target:$bucket" || die "rclone copy failed; re-run to resume"

  local dst dst_count dst_bytes ok=1
  dst="$(rclone_run size --json "target:$bucket" 2>/dev/null | parse_rclone_size)"
  read -r dst_count dst_bytes <<<"$dst"
  log "target target:$bucket — $dst_count object(s), $dst_bytes bytes"
  if [[ "$dst_count" == "$src_count" && "$dst_bytes" == "$src_bytes" ]]; then
    log "PASS count and size match"
  elif ((dst_count > src_count)); then
    log "WARN the target holds more objects than the source (uploads made after the switch?)"
  else
    log "FAIL count/size mismatch"
    ok=0
  fi
  if rclone_run check --one-way --size-only "legacy:$bucket" "target:$bucket" >/dev/null 2>&1; then
    log "PASS every source object exists on the target with the same size"
  else
    log "FAIL some source objects are missing or differ (re-run to resume the copy)"
    ok=0
  fi
  if [[ "$sample" -gt 0 ]]; then
    rclone_run lsf -R --files-only "legacy:$bucket" 2>/dev/null |
      awk 'BEGIN {srand()} {print rand() "\t" $0}' | sort | head -n "$sample" | cut -f2- \
      >"$WORK/sample.txt"
    if rclone_run check --one-way --download --files-from /work/sample.txt \
      "legacy:$bucket" "target:$bucket" >/dev/null 2>&1; then
      log "PASS content of $(wc -l <"$WORK/sample.txt" | tr -d ' ') sampled object(s) is identical"
    else
      log "FAIL sampled content differs"
      ok=0
    fi
  fi
  [[ $ok -eq 1 ]] || die "verification failed; the old volume $volume is untouched"
  log "done; keep $volume until the new stack has run for a while, then remove it yourself"
}

if [[ -z "${UPGRADE_LIB_ONLY:-}" ]]; then
  main "$@"
fi
