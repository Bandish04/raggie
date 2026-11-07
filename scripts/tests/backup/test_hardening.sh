# SPDX-License-Identifier: Apache-2.0
# shellcheck shell=bash
# Review findings M1-M4, L1-L3, L7: retention, manifest scope, fail-closed stack
# checks, unchecked helper output, names used in paths, permissions.

# shellcheck source=test_backup.sh
. "$TESTS_DIR/test_backup.sh"

listed_without() { # BACKUP PATH: drop PATH from the manifest's artifacts
  python3 - "$1/manifest.json" "$2" <<'PY'
import json, sys
p, drop = sys.argv[1], sys.argv[2]
d = json.load(open(p))
d["artifacts"] = [a for a in d["artifacts"] if a["path"] != drop]
json.dump(d, open(p, "w"))
PY
}

no_pg_restore() { assert_not_contains "$(cat "$FAKE_LOG")" "pg_restore" "nothing may be restored"; }

# ── M1: retention ────────────────────────────────────────────────────────────
test_retention_never_expands_globs() {
  mkdir -p "$T/backups/raggie-backup-0 *" "$T/install/keepme"
  echo '{}' >"$T/backups/raggie-backup-0 */manifest.json"
  echo '{}' >"$T/install/keepme/manifest.json"
  backup --retention 1
  [[ -f "$T/install/keepme/manifest.json" ]] || fail_test "a directory in the CWD was removed"
  [[ -f "$T/install/.env" ]] || fail_test ".env was removed"
  [[ -d "$T/backups/raggie-backup-0 *" ]] || fail_test "a name this tool never writes was pruned"
}

test_retention_keeps_symlinks_foreign_and_the_new_backup() {
  mkdir -p "$T/elsewhere/raggie-backup-20200101T000000Z" "$T/backups/raggie-backup-foreign" \
    "$T/backups/raggie-backup-20991231T000000Z"
  echo '{}' >"$T/elsewhere/raggie-backup-20200101T000000Z/manifest.json"
  echo '{}' >"$T/backups/raggie-backup-foreign/manifest.json"
  echo '{}' >"$T/backups/raggie-backup-20991231T000000Z/manifest.json"
  ln -s "$T/elsewhere/raggie-backup-20200101T000000Z" "$T/backups/raggie-backup-20200102T000000Z"
  local b
  b="$(backup --retention 1 | tail -n1)"
  [[ -f "$b/manifest.json" ]] || fail_test "the backup just written was pruned"
  [[ -L "$T/backups/raggie-backup-20200102T000000Z" ]] || fail_test "a symlink was pruned"
  [[ -f "$T/elsewhere/raggie-backup-20200101T000000Z/manifest.json" ]] || fail_test "a symlink was followed"
  [[ -d "$T/backups/raggie-backup-foreign" ]] || fail_test "a foreign directory was pruned"
  # The only other real backup is the (future-dated) one: retention 1 removes it.
  [[ ! -e "$T/backups/raggie-backup-20991231T000000Z" ]] || fail_test "an old backup was kept"
}

test_retention_works_with_spaces_in_the_out_path() {
  local out="$T/my backups"
  mkdir -p "$out/raggie-backup-20200101T000000Z"
  echo '{}' >"$out/raggie-backup-20200101T000000Z/manifest.json"
  "$BACKUP" --compose "$COMPOSE" --out "$out" --retention 1 >/dev/null
  [[ ! -e "$out/raggie-backup-20200101T000000Z" ]] || fail_test "nothing was pruned under a path with spaces"
  assert_eq "$(find "$out" -mindepth 1 -maxdepth 1 -name 'raggie-backup-*' | wc -l | tr -d ' ')" 1
}

# ── L7: permissions ──────────────────────────────────────────────────────────
test_backup_files_are_private() {
  backup
  local b
  b="$(latest)"
  assert_eq "$(file_mode "$b/postgres.dump")" 600 "postgres.dump"
  assert_eq "$(file_mode "$b/qdrant/raggie_chunks_d1024.snapshot")" 600 "snapshot"
  assert_eq "$(file_mode "$b/objects.sha256")" 600 "objects.sha256"
}

test_backup_refuses_an_out_dir_owned_by_someone_else() {
  [[ "$(id -u)" != 0 ]] || return 0 # root owns everything
  expect_fail "$BACKUP" --compose "$COMPOSE" --out /
  assert_contains "$FAIL_OUT" "not owned by"
}

# ── M4: unchecked helper output ──────────────────────────────────────────────
test_backup_fails_when_the_object_count_cannot_be_read() {
  FAKE_RCLONE_SIZE_FAIL=1 expect_fail backup
  assert_contains "$FAIL_OUT" "object store"
}

test_backup_fails_when_qdrant_cannot_list_collections() {
  FAKE_QDRANT_LIST_FAIL=1 expect_fail backup
  assert_contains "$FAIL_OUT" "Qdrant collections"
}

test_backup_refuses_zero_collections_with_indexed_documents() {
  FAKE_COLLECTIONS="" expect_fail backup
  assert_contains "$FAIL_OUT" "no Qdrant collection"
}

test_restore_refuses_an_empty_fingerprint_unless_allowed() {
  FAKE_FP="" backup
  FAKE_RUNNING="" expect_fail restore --yes "$(latest)"
  assert_contains "$FAIL_OUT" "--allow-no-fingerprint"
  no_pg_restore
  FAKE_RUNNING="" restore --yes --allow-no-fingerprint "$(latest)"
  assert_eq "$(cat "$FAKE_STATE/restored.dump")" "PGDUMP-CONTENT"
}

# ── L3: snapshot names ───────────────────────────────────────────────────────
test_backup_refuses_an_unexpected_snapshot_name() {
  FAKE_SNAPSHOT_NAME="../../evil" expect_fail backup
  assert_contains "$FAIL_OUT" "snapshot name"
  assert_not_contains "$(cat "$FAKE_LOG")" "DELETE " "no DELETE with an unchecked name"
}

# ── M3: the running-stack refusal fails closed ───────────────────────────────
test_restore_refuses_when_compose_ps_fails() {
  backup
  : >"$FAKE_LOG"
  FAKE_RUNNING="" FAKE_PS_FAIL=1 expect_fail restore --yes "$(latest)"
  assert_contains "$FAIL_OUT" "cannot read the state"
  no_pg_restore
}

test_restore_counts_restarting_and_created_as_running() {
  backup
  local st
  for st in restarting created paused; do
    : >"$FAKE_LOG"
    FAKE_RUNNING="" FAKE_STATES="edge=$st" expect_fail restore --yes "$(latest)"
    assert_contains "$FAIL_OUT" "edge"
    no_pg_restore
  done
  FAKE_RUNNING="" FAKE_PS_ARRAY=1 FAKE_STATES="web=running" expect_fail restore --yes "$(latest)"
  assert_contains "$FAIL_OUT" "web"
  FAKE_RUNNING="" FAKE_STATES="edge=exited web=exited" restore --yes "$(latest)"
  assert_eq "$(cat "$FAKE_STATE/restored.dump")" "PGDUMP-CONTENT"
}

test_restore_rechecks_the_stack_before_pg_restore() {
  backup
  : >"$FAKE_LOG"
  FAKE_RUNNING="" FAKE_STATES_AFTER_UP="control-plane=running" expect_fail restore --yes "$(latest)"
  assert_contains "$FAIL_OUT" "control-plane"
  no_pg_restore
}

# ── M2: everything restored is listed, nothing unlisted is present ──────────
test_verify_rejects_unlisted_files() {
  backup
  local b
  b="$(latest)"
  printf 'x' >"$b/extra.sh"
  FAKE_RUNNING="" expect_fail restore --yes "$b"
  assert_contains "$FAIL_OUT" "unlisted: extra.sh"
  rm "$b/extra.sh"
  printf 'x' >"$b/objects/uploads/evil.pdf"
  FAKE_RUNNING="" expect_fail restore --yes "$b"
  assert_contains "$FAIL_OUT" "unlisted: objects/uploads/evil.pdf"
  rm "$b/objects/uploads/evil.pdf"
  ln -s /etc/hosts "$b/qdrant/link.snapshot"
  FAKE_RUNNING="" expect_fail restore --yes "$b"
  assert_contains "$FAIL_OUT" "symlink: qdrant/link.snapshot"
  no_pg_restore
}

test_restore_requires_what_it_restores_to_be_listed() {
  local p
  for p in postgres.dump qdrant/raggie_chunks_d1024.snapshot objects.sha256; do
    backup
    listed_without "$(latest)" "$p"
    : >"$FAKE_LOG"
    FAKE_RUNNING="" expect_fail restore --yes "$(latest)"
    assert_contains "$FAIL_OUT" "not listed: $p"
    no_pg_restore
    rm -rf "$(latest)"
  done
}

# ── L2: collection names from the manifest ──────────────────────────────────
test_restore_refuses_an_unsafe_collection_name() {
  backup
  python3 - "$(latest)/manifest.json" <<'PY'
import json, sys
p = sys.argv[1]
d = json.load(open(p))
d["qdrant"][0]["collection"] = "../evil"
json.dump(d, open(p, "w"))
PY
  FAKE_RUNNING="" expect_fail restore --yes "$(latest)"
  assert_contains "$FAIL_OUT" "collection name"
  no_pg_restore
}

# ── M2 (optional): HMAC over manifest.json ──────────────────────────────────
test_manifest_hmac_is_written_and_checked() {
  BACKUP_MANIFEST_KEY=k1 backup
  local b
  b="$(latest)"
  [[ -f "$b/manifest.json.hmac" ]] || fail_test "no manifest.json.hmac"
  assert_eq "$(file_mode "$b/manifest.json.hmac")" 600
  BACKUP_MANIFEST_KEY=k1 FAKE_RUNNING="" restore --yes "$b"
  BACKUP_MANIFEST_KEY=other FAKE_RUNNING="" expect_fail restore --yes "$b"
  assert_contains "$FAIL_OUT" "HMAC mismatch"
  sed -i.bak 's/"documents": 3/"documents": 4/' "$b/manifest.json" && rm -f "$b/manifest.json.bak"
  BACKUP_MANIFEST_KEY=k1 FAKE_RUNNING="" expect_fail restore --yes "$b"
  assert_contains "$FAIL_OUT" "HMAC mismatch"
  backup
  BACKUP_MANIFEST_KEY=k1 FAKE_RUNNING="" expect_fail restore --yes "$(latest)"
  assert_contains "$FAIL_OUT" "not signed"
}

# ── L1: verify late, refuse writable backup dirs ────────────────────────────
test_restore_verifies_after_the_confirmation() {
  backup
  : >"$FAKE_LOG"
  FAKE_RUNNING="" FAKE_TAMPER_ON_UP="$(latest)/postgres.dump" expect_fail restore --yes "$(latest)"
  assert_contains "$FAIL_OUT" "sha256 mismatch: postgres.dump"
  no_pg_restore
}

test_restore_refuses_a_group_or_world_writable_backup() {
  backup
  local b
  b="$(latest)"
  chmod g+w "$b"
  FAKE_RUNNING="" expect_fail restore --yes "$b"
  assert_contains "$FAIL_OUT" "writable"
  chmod g-w "$b"
  chmod o+w "$b/qdrant"
  FAKE_RUNNING="" expect_fail restore --yes "$b"
  assert_contains "$FAIL_OUT" "writable"
  no_pg_restore
}
