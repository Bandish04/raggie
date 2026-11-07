# Disaster-recovery drill

A full backup → restore → answer cycle on the Docker Compose stack.
[`scripts/dr-drill.sh`](../../scripts/dr-drill.sh) runs it and rewrites the
results block below. The weekly
[`dr-drill`](../../.github/workflows/dr-drill.yml) workflow runs the same script
and uploads this file as an artifact; commit a run you want to quote.

## Setup

| | |
|---|---|
| Stack | `scripts/e2e-stack.sh`: production mode, freshly generated strong secrets, deterministic mock LLM, local embeddings |
| Source | compose project `raggie-drill-src`: bootstrapped admin, one INTERNAL workspace, the e2e fixture PDF ingested |
| Backup | `scripts/backup.sh`: `pg_dump -Fc`, a Qdrant snapshot per collection, the bucket copied with rclone, `manifest.json` with sha256 |
| Disaster | the source project is stopped; its volumes are not used again |
| Target | compose project `raggie-drill-dst`: new volumes, same configuration, restored with `scripts/restore.sh --yes` |

## Pass criteria

1. Every artifact matches its sha256 in the manifest (the restore refuses otherwise).
2. The restored schema version and the counts of live documents and users equal the manifest's.
3. After signing in again, the golden question ("How many days of annual leave do employees get?") gets an answer that cites the fixture (`event: sources` names it, the text carries `[1]`).

## Measures

- **Backup duration**: the window in which writes may be missing from the backup.
  The RPO of a scheduled backup is its interval plus this duration.
- **Restore**: from `restore.sh` start to the end of the data restore (verify,
  start the datastores and the embeddings gateway, Postgres, Qdrant, files).
- **RTO**: from the start of the restore to the first cited answer on the
  restored stack (includes starting every service).

## Results

<!-- dr-drill:results:start -->
Not run yet. Start the `dr-drill` workflow (Actions → DR drill → Run workflow)
or run `scripts/dr-drill.sh` on a machine with Docker.
<!-- dr-drill:results:end -->
