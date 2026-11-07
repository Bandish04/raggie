# Backup and restore

What to back up, how to restore it, and how to rehearse. The commands target the
single-server Docker Compose stack (project name `raggie`); Kubernetes notes are
at the end.

Raggie ships three scripts for this, run from the install directory (they use
`.raggie/compose` when the installer created it):

| Script | What it does |
|---|---|
| [`scripts/backup.sh`](../scripts/backup.sh) | Postgres dump, Qdrant snapshots, a copy of the uploaded files (local or S3), optionally `.env`, and a `manifest.json` with the sha256 of every artifact |
| [`scripts/restore.sh`](../scripts/restore.sh) | Verifies the manifest, refuses while the app is running or when the embedding model differs, then restores Postgres, vectors and files |
| [`scripts/dr-drill.sh`](../scripts/dr-drill.sh) | The full drill on throwaway stacks: backup, restore into a new compose project, schema check, a cited answer, RPO/RTO timings ([results](benchmarks/dr-drill.md)) |

`--help` on each script lists every option.

## What holds state

| Store | Contents | Source of truth? | Backup method |
|---|---|---|---|
| PostgreSQL | users, organizations, workspaces, document metadata, conversations, messages, audit log, settings | **Yes**, back up first | `pg_dump` (or WAL archiving for point-in-time recovery) |
| Object store: bundled SeaweedFS (service `objectstore`, volume `objectstore_data`) or your own S3 service; bucket `MINIO_BUCKET`, default `raggie-uploads` | the original uploaded files | **Yes** for document content | any S3 client (`mc mirror`, `rclone sync`) or volume snapshot |
| Qdrant | chunks, vectors and payload for search | No, rebuildable from Postgres + the object store | snapshot API (faster than rebuilding) |
| Valkey (service `redis`, volume `valkey_data`) | caches, rate-limit counters, event streams (pending jobs) | No | optional (AOF is enabled in compose) |
| `.env`, `.env.embeddings` | secrets and configuration | **Yes** | encrypted copy kept separately |

Back up `.env` with the data. Without `INTEGRATION_ENC_KEY` stored integration
credentials cannot be decrypted, and without `JWT_SECRET` all sessions end (users
simply sign in again).

Backups contain personal data and document text. Encrypt them, restrict access,
and include them in your retention and erasure procedures
([data-handling.md](data-handling.md)).

## Suggested objectives

Reasonable targets for a single server; adjust to your needs and measure them in a
drill:

| Store | RPO (data loss) | RTO (downtime) |
|---|---|---|
| PostgreSQL | ≤ 24 h with nightly dumps, minutes with WAL archiving | ≤ 1 h |
| Object store | ≤ 24 h | ≤ 2 h |
| Qdrant | rebuildable; snapshots only shorten recovery | ≤ 1 h from a snapshot, longer for a full re-embed |

## Backup

```bash
cd /opt/raggie                       # the install directory, where .env lives
scripts/backup.sh                    # → ~/raggie-backups/raggie-backup-<UTC time>/
```

The datastores must be running; the app can keep serving (`pg_dump` is
consistent and Qdrant snapshots each collection). Everything is written with
`umask 077`. A backup directory (mode 700) holds:

| File | Contents |
|---|---|
| `postgres.dump` | `pg_dump -Fc` of the database |
| `qdrant/<collection>.snapshot` | a snapshot of every Qdrant collection |
| `objects/` + `objects.sha256` | the uploaded files, copied with a pinned `rclone` image, and the sha256 of each |
| `env/` | only with `--include-env`: `.env` and `.env.embeddings`, mode 600 |
| `manifest.json` | Raggie version, schema version, embedding fingerprint and collection, document/user/workspace counts, object count and size, the sha256 of every artifact |
| `manifest.json.hmac` | only with `BACKUP_MANIFEST_KEY` set: an HMAC-SHA256 of `manifest.json` |

Options worth knowing:

- `--out DIR`: where backups go (default `~/raggie-backups`, outside the
  install directory so an upgrade that replaces it cannot touch them). The
  directory must be owned by the user running the backup.
- `--retention N`: keep only the N newest backups in that directory, the new
  one included. Only real directories directly in it, named exactly like the
  ones this script writes (`raggie-backup-YYYYMMDDTHHMMSSZ`, optionally `-N`)
  and holding a `manifest.json`, are ever removed; symlinks, other names and
  the backup just written never are.
- `--objects-dest s3:BUCKET/PREFIX`: copy the files to an S3 target instead of
  the backup directory (set `BACKUP_S3_ENDPOINT`, `BACKUP_S3_ACCESS_KEY_ID`,
  `BACKUP_S3_SECRET_ACCESS_KEY`, optionally `BACKUP_S3_REGION` and
  `BACKUP_S3_PROVIDER`). The manifest records where they went.
- `--include-env`: adds the secrets. Without `INTEGRATION_ENC_KEY` stored
  integration credentials cannot be decrypted, and without `JWT_SECRET` every
  session ends, so a disaster-recovery copy needs them. A backup with secrets
  must be encrypted, for example
  `tar -C ~/raggie-backups -cf - raggie-backup-… | gpg --symmetric -o raggie-backup-….tar.gpg`.
- `--skip-qdrant` (vectors can be rebuilt, see `restore.sh --reindex`) and
  `--skip-objects`.

The backup fails instead of writing an incomplete manifest when it cannot read
something it records: the object count, the Qdrant collection list, a point
count. It also fails when Qdrant has no collection (or not the active one)
while Postgres has indexed documents, which usually means it is talking to the
wrong Qdrant (`--skip-qdrant` backs up without vectors on purpose).

To detect a tampered manifest, set `BACKUP_MANIFEST_KEY` (a long random
string, kept outside the backup, for example in the cron environment). The
backup then signs `manifest.json` (`manifest.json.hmac`), and a restore with the
same key set refuses a manifest that is unsigned or does not match. Without the
key, the sha256 values only detect accidental corruption: whoever can rewrite
the backup can rewrite the manifest too.

The script never deletes source data: rclone only copies, and the only Qdrant
call that deletes removes the snapshot it has just downloaded. Secrets reach
`curl` and `rclone` through a 0600 header file or environment variables, never
a command line.

Schedule it with cron, for example nightly with a week of history:

```cron
15 2 * * * cd /opt/raggie && scripts/backup.sh --retention 7 >>/var/log/raggie-backup.log 2>&1
```

Then copy `~/raggie-backups` off the machine (rsync, restic, your backup
system). For point-in-time recovery of Postgres, add WAL archiving
(`archive_mode=on` with pgBackRest, WAL-G or `archive_command`); the nightly
dump then serves as the base backup.

## Restore

Restore onto the **same Raggie version** that made the backup (the manifest
records it), then upgrade if needed ([upgrade.md](upgrade.md)).

```bash
cd /opt/raggie
.raggie/compose down                 # stop the app; never `down -v`
cp ~/raggie-backups/raggie-backup-…/env/.env .env   # new machine only (backups made with --include-env)
scripts/restore.sh ~/raggie-backups/raggie-backup-…
.raggie/compose up -d
```

In order, `restore.sh`:

1. refuses a backup directory in which anything is group- or world-writable,
   then verifies it against `manifest.json`: `postgres.dump`, every snapshot it
   will upload and `objects.sha256` must be listed, every listed file must
   match its sha256 (each file in `objects/` through `objects.sha256`), and any
   unlisted file or symlink fails the check. With `BACKUP_MANIFEST_KEY` set, the
   manifest's HMAC must match too;
2. refuses while any application service (web, edge, control-plane, the
   workers, caddy) has a container that is not exited (restarting or created
   count as running), and when it cannot read the compose state at all;
3. starts the datastores and the embeddings gateway, and refuses when the
   gateway's embedding fingerprint differs from the backup's, because the
   snapshots would hold vectors of another model. A backup that records no
   fingerprint is refused unless you pass `--allow-no-fingerprint` (restore
   the vectors as they are) or `--reindex`;
4. asks you to type `RESTORE` (or takes `--yes`), verifies the backup and the
   stopped stack once more, then overwrites the
   database (`pg_restore --clean --if-exists`) and the Qdrant collections in the
   backup (snapshot upload), and copies the files back into the bucket. Objects
   that are not in the backup are kept.

`--reindex` restores without the vector snapshots instead. It re-publishes
every live document through `python -m raggie_control_plane.reindex`, and the
ingestion workers re-embed them with the current model once the stack is up.
Use it after changing the embedding model, or when the backup has no
snapshots. It is slower and, with a cloud embedding provider, costs one
embedding pass over every document.

Then smoke test: sign in, open a known document, and ask a question whose
answer cites it.

Valkey is not backed up: it only holds caches, rate limits and the event
streams. Documents that were still processing at backup time lost their queued
events. The scheduler worker's stale-document sweep recovers them on its own:
every live document that has stayed *Pending* or *Processing* for longer than
`STALE_PENDING_SECONDS` (default 900 s, at most `STALE_PENDING_BATCH` per tick)
is re-published. Workers heartbeat the documents they are processing
(`INGEST_HEARTBEAT_SECONDS`), so active work is never mistaken for stuck work.
Documents that ended *Failed* are retried with back-off, or immediately with
*Retry failed* in the knowledge base.

## Volume-level backups

With the stack **stopped** (`$C down`, never `down -v`), you can also archive the
Docker volumes directly:

```bash
for v in postgres_data objectstore_data qdrant_data; do
  docker run --rm -v "raggie_$v:/data:ro" -v "$PWD:/backup" alpine \
    tar czf "/backup/raggie-$v-$DAY.tgz" -C /data .
done
```

This is simple and consistent, but needs downtime and restores only to the same
datastore versions.

## Restore drill

A backup counts only once it has been restored. `scripts/dr-drill.sh` runs the
whole cycle on throwaway stacks:

1. seed a stack;
2. back it up;
3. stop it;
4. restore into a second compose project with new volumes;
5. compare the schema version and counts with the manifest;
6. ask the golden question until the answer cites the source document.

It records the backup window, the restore duration and the RTO in
[benchmarks/dr-drill.md](benchmarks/dr-drill.md). CI runs it weekly
([`dr-drill.yml`](../.github/workflows/dr-drill.yml)).

For your own installation, restore the latest real backup on a scratch machine
every quarter (and after changing the backup setup). Run the smoke test above
and compare the measured RPO/RTO with your objectives.

## Kubernetes

The scripts target Docker Compose. On Kubernetes, use each datastore's native
tooling:

- **PostgreSQL**: the Helm `ha` profile runs CloudNativePG. Enable its Barman
  object-store backups (`spec.backup.barmanObjectStore`, plus a
  `ScheduledBackup`) for base backups with continuous WAL archiving, which gives
  point-in-time recovery. Restore by bootstrapping a new `Cluster` from the
  backup (`bootstrap.recovery`). Without CNPG, run `pg_dump -Fc` from a CronJob.
- **Qdrant**: call the snapshot API per collection from a CronJob (the same
  calls `backup.sh` makes: `POST /collections/{name}/snapshots`, then download).
  Qdrant can also write snapshots to S3 itself
  (`storage.snapshots_config` in its configuration). Restore with `POST /collections/{name}/snapshots/upload?priority=snapshot`.
- **Object store**: replicate or back up the bucket with your S3 provider's
  tooling, or with `rclone copy` from a CronJob.
- **Secrets**: back up the Kubernetes Secrets (or the sealed-secrets / Vault
  source) with the data.

A drill works the same way: restore into a new namespace, then run the smoke
test. Managed PostgreSQL and S3 services simplify all of this considerably.
