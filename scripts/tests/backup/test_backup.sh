# SPDX-License-Identifier: Apache-2.0
# shellcheck shell=bash
# scripts/backup.sh and scripts/restore.sh against the fakes (see run.sh).

BACKUP="$REPO_ROOT/scripts/backup.sh"
RESTORE="$REPO_ROOT/scripts/restore.sh"

backup() { "$BACKUP" --compose "$COMPOSE" --out "$T/backups" "$@"; }
restore() { "$RESTORE" --compose "$COMPOSE" "$@"; }
latest() { find "$T/backups" -maxdepth 1 -name 'raggie-backup-*' -type d | sort | tail -n1; }
mf() { python3 -c 'import json,sys; d=json.load(open(sys.argv[1]))
for k in sys.argv[2].split("."): d=d[int(k)] if isinstance(d,list) else d[k]
print(d)' "$1/manifest.json" "$2"; }
sha() { python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$1"; }

test_backup_writes_a_verifiable_manifest() {
  backup
  local b
  b="$(latest)"
  assert_eq "$(cat "$b/postgres.dump")" "PGDUMP-CONTENT"
  assert_eq "$(cat "$b/qdrant/raggie_chunks_d1024.snapshot")" "SNAPSHOT-raggie_chunks_d1024"
  assert_eq "$(cat "$b/objects/uploads/ws1/b.txt")" "file two!"
  assert_eq "$(mf "$b" format)" 1
  assert_eq "$(mf "$b" schema_version)" 0027
  assert_eq "$(mf "$b" embeddings.fingerprint)" 2872ae6a
  assert_eq "$(mf "$b" embeddings.collection)" raggie_chunks_d1024
  assert_eq "$(mf "$b" counts.documents)" 3
  assert_eq "$(mf "$b" counts.users)" 2
  assert_eq "$(mf "$b" objects.count)" 2
  assert_eq "$(mf "$b" objects.bytes)" 17
  assert_eq "$(mf "$b" objects.location)" objects
  assert_eq "$(mf "$b" qdrant.0.collection)" raggie_chunks_d1024
  assert_eq "$(mf "$b" qdrant.0.points)" 42
  assert_eq "$(mf "$b" include_env)" False
  # Every artifact is hashed, objects through objects.sha256.
  local listed
  listed="$(python3 -c 'import json,sys; print(" ".join(sorted(a["path"] for a in json.load(open(sys.argv[1]))["artifacts"])))' "$b/manifest.json")"
  assert_eq "$listed" "objects.sha256 postgres.dump qdrant/raggie_chunks_d1024.snapshot"
  assert_eq "$(python3 -c 'import json,sys; print([a["sha256"] for a in json.load(open(sys.argv[1]))["artifacts"] if a["path"]=="postgres.dump"][0])' "$b/manifest.json")" \
    "$(sha "$b/postgres.dump")"
  assert_contains "$(cat "$b/objects.sha256")" "$(sha "$b/objects/uploads/ws1/a.pdf")  uploads/ws1/a.pdf"
  assert_eq "$(file_mode "$b")" 700
}

test_backup_keeps_secrets_off_command_lines() {
  backup
  local log
  log="$(cat "$FAKE_LOG")"
  assert_contains "$log" "api-key=yes"
  assert_not_contains "$log" "api-key=argv"
  assert_not_contains "$log" "qdrant-secret-key"
  assert_not_contains "$log" "minio-secret-password"
}

test_backup_never_deletes_source_data() {
  backup
  backup
  assert_eq "$(cat "$FAKE_BUCKET_DIR/raggie-uploads/uploads/ws1/a.pdf")" "file one"
  local log
  log="$(cat "$FAKE_LOG")"
  local rclone_calls
  rclone_calls="$(grep 'rclone/rclone' "$FAKE_LOG")"
  for verb in sync move moveto delete deletefile purge rmdirs cleanup; do
    assert_not_contains "$rclone_calls" " $verb " "rclone $verb"
  done
  # Only the snapshot just downloaded is removed from Qdrant, never a collection.
  assert_eq "$(grep -c '^DELETE ' "$FAKE_LOG")" 2
  assert_eq "$(grep '^DELETE ' "$FAKE_LOG" | grep -vc '/snapshots/snap-1.snapshot ')" 0
  assert_not_contains "$log" "down"
}

test_backup_to_an_s3_target() {
  BACKUP_S3_ENDPOINT=https://s3.example.com BACKUP_S3_ACCESS_KEY_ID=ak BACKUP_S3_SECRET_ACCESS_KEY=sk \
    backup --objects-dest s3:offsite-bucket/raggie
  local b
  b="$(latest)"
  assert_contains "$(mf "$b" objects.location)" "s3:offsite-bucket/raggie/raggie-backup-"
  assert_eq "$(find "$FAKE_S3_DIR" -type f | wc -l | tr -d ' ')" 2
  [[ ! -e "$b/objects" ]] || fail_test "no local object copy expected"
  assert_not_contains "$(cat "$FAKE_LOG")" "BACKUP_S3_SECRET_ACCESS_KEY=sk"
}

test_include_env_is_private_and_loud() {
  local out
  out="$(backup --include-env 2>&1)"
  assert_contains "$out" "SECRETS"
  local b
  b="$(latest)"
  assert_eq "$(file_mode "$b/env/.env")" 600
  assert_eq "$(mf "$b" include_env)" True
  assert_contains "$(python3 -c 'import json,sys; print([a["path"] for a in json.load(open(sys.argv[1]))["artifacts"]])' "$b/manifest.json")" "env/.env"
}

test_retention_keeps_the_newest_backups_only() {
  mkdir -p "$T/backups/raggie-backup-20200101T000000Z" "$T/backups/raggie-backup-20200102T000000Z" \
    "$T/backups/raggie-backup-20200103T000000Z" "$T/backups/raggie-backup-19990101T000000Z" \
    "$T/backups/unrelated"
  for d in 20200101 20200102 20200103; do echo '{}' >"$T/backups/raggie-backup-${d}T000000Z/manifest.json"; done
  backup --retention 2
  local left
  left="$(find "$T/backups" -mindepth 1 -maxdepth 1 -exec basename {} \; | tr '\n' ' ')"
  assert_contains "$left" "raggie-backup-20200103T000000Z"
  assert_not_contains "$left" "raggie-backup-20200102T000000Z"
  assert_not_contains "$left" "raggie-backup-20200101T000000Z"
  # Directories this tool did not write (no manifest.json) are never removed.
  assert_contains "$left" "raggie-backup-19990101T000000Z"
  assert_contains "$left" "unrelated"
  [[ -f "$(latest)/manifest.json" ]] || fail_test "the new backup must survive"
}

test_backup_refuses_when_the_datastores_are_down() {
  FAKE_RUNNING="redis" expect_fail backup
  assert_contains "$FAIL_OUT" "postgres"
}

test_restore_round_trip() {
  backup
  rm -rf "${FAKE_BUCKET_DIR:?}/raggie-uploads"
  FAKE_RUNNING="" restore --yes "$(latest)"
  assert_eq "$(cat "$FAKE_STATE/restored.dump")" "PGDUMP-CONTENT"
  assert_eq "$(cat "$FAKE_BUCKET_DIR/raggie-uploads/uploads/ws1/a.pdf")" "file one"
  assert_contains "$(cat "$FAKE_LOG")" "/collections/raggie_chunks_d1024/snapshots/upload?priority=snapshot"
  assert_contains "$(cat "$FAKE_LOG")" "pg_restore"
  assert_contains "$(cat "$FAKE_LOG")" "--clean --if-exists"
  assert_not_contains "$(cat "$FAKE_LOG")" "raggie_control_plane.reindex"
}

test_restore_refuses_a_tampered_backup() {
  backup
  printf 'evil' >>"$(latest)/postgres.dump"
  FAKE_RUNNING="" expect_fail restore --yes "$(latest)"
  assert_contains "$FAIL_OUT" "sha256 mismatch: postgres.dump"
  [[ ! -e "$FAKE_STATE/restored.dump" ]] || fail_test "nothing may be restored"
  assert_not_contains "$(cat "$FAKE_LOG")" "compose up"
}

test_restore_refuses_a_tampered_object() {
  backup
  printf 'x' >>"$(latest)/objects/uploads/ws1/a.pdf"
  FAKE_RUNNING="" expect_fail restore --yes "$(latest)"
  assert_contains "$FAIL_OUT" "sha256 mismatch: objects/uploads/ws1/a.pdf"
}

test_restore_refuses_a_running_stack() {
  backup
  : >"$FAKE_LOG"
  FAKE_RUNNING="postgres control-plane web" expect_fail restore --yes "$(latest)"
  assert_contains "$FAIL_OUT" "control-plane"
  assert_not_contains "$(cat "$FAKE_LOG")" "pg_restore"
  assert_not_contains "$(cat "$FAKE_LOG")" "compose up"
}

test_restore_refuses_a_fingerprint_mismatch_unless_reindex() {
  backup
  FAKE_RUNNING="" FAKE_GATEWAY_FP=5e1f00d2 expect_fail restore --yes "$(latest)"
  assert_contains "$FAIL_OUT" "fingerprint"
  [[ ! -e "$FAKE_STATE/restored.dump" ]] || fail_test "nothing may be restored"

  : >"$FAKE_LOG"
  FAKE_RUNNING="" FAKE_GATEWAY_FP=5e1f00d2 restore --yes --reindex "$(latest)"
  assert_eq "$(cat "$FAKE_STATE/restored.dump")" "PGDUMP-CONTENT"
  assert_not_contains "$(cat "$FAKE_LOG")" "snapshots/upload"
  assert_contains "$(cat "$FAKE_LOG")" "raggie_control_plane.reindex"
}

test_restore_needs_an_explicit_confirmation() {
  backup
  FAKE_RUNNING="" RAGGIE_TTY=/nonexistent expect_fail restore "$(latest)"
  assert_contains "$FAIL_OUT" "--yes"
  [[ ! -e "$FAKE_STATE/restored.dump" ]] || fail_test "nothing may be restored"
  printf 'nope\n' >"$T/tty"
  FAKE_RUNNING="" RAGGIE_TTY="$T/tty" expect_fail restore "$(latest)"
  printf 'RESTORE\n' >"$T/tty"
  FAKE_RUNNING="" RAGGIE_TTY="$T/tty" restore "$(latest)"
  assert_eq "$(cat "$FAKE_STATE/restored.dump")" "PGDUMP-CONTENT"
}
