# Disaster recovery

The runbook lives in **[backup-restore.md](backup-restore.md)**: what holds
state, the objectives, and how to use the scripts.

The short version for a Docker Compose install:

```bash
scripts/backup.sh --retention 7 --include-env     # nightly; encrypt and ship ~/raggie-backups off-site
.raggie/compose down                              # disaster: stop the app (never down -v)
scripts/restore.sh ~/raggie-backups/raggie-backup-<time>
.raggie/compose up -d
```

`scripts/dr-drill.sh` rehearses the whole cycle. The latest measured RPO/RTO
is in [benchmarks/dr-drill.md](benchmarks/dr-drill.md). For Kubernetes (CNPG
Barman backups, Qdrant snapshots), see
[backup-restore.md](backup-restore.md#kubernetes).
