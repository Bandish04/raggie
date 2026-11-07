# Upgrading

Raggie follows semantic versioning. While the version is `0.x`, minor releases
may include breaking changes; they are called out in [CHANGELOG.md](../CHANGELOG.md).

## Before every upgrade

1. **Read the changelog** for every version between yours and the target,
   especially the *Changed*, *Removed* and *Security* sections.
2. **Back up** Postgres, the uploaded files and `.env`
   ([backup-restore.md](backup-restore.md)). Migrations are forward-only, so the
   backup **is** your rollback.
3. **Compare configuration.** New settings arrive in `.env.example` with safe
   defaults, but your existing `.env` is never modified:
   ```bash
   diff <(grep -oE '^[A-Z][A-Z0-9_]*' .env.example | sort -u) \
        <(grep -oE '^[A-Z][A-Z0-9_]*' .env | sort -u)
   ```
   Lines starting with `<` are new variables you may want to set. The
   [configuration reference](configuration.md) explains each one.

## Docker Compose (from source)

```bash
git fetch --tags && git checkout vX.Y.Z      # or: git pull on main (not recommended for production)
C="docker compose -f deploy/compose/docker-compose.yml --env-file .env"
$C --profile core build
$C --profile core up -d
```

The control plane applies pending database migrations when it starts. Watch it
with `$C logs -f control-plane`; the web UI becomes ready after migrations finish.
To run migrations explicitly (for example before scaling up), use `make migrate`.

## Installer

Re-running the installer on a host where Raggie is installed is an upgrade:

```bash
curl -fsSL https://github.com/alicangunduz/raggie/releases/latest/download/install.sh | sudo bash
```

It downloads the pinned, sha256-verified release (`--version X.Y.Z` for a
specific one), backs up `.env` and `.env.embeddings`, adds only the new keys to
them (existing values are never overwritten) and restarts the stack. Use
`--reconfigure` to answer the embeddings and LLM questions again.

## Kubernetes

- **Helm** (`deploy/helm/raggie`): `helm upgrade` with your values file; the chart
  includes a migration Job so application pods do not race to migrate.
- **Kustomize** (`deploy/k8s`): bump the image tags in your overlay and apply.
  Migrations run at control-plane start-up and are serialized with a Postgres
  advisory lock, so several replicas starting together is safe.

## Upgrading to 0.1.0 (Valkey and SeaweedFS)

Installs from before 0.1.0 ran Redis 7 and MinIO. 0.1.0 bundles **Valkey 8**
and **SeaweedFS** instead. Both keep the old wiring (the Valkey service is still
called `redis`, and the object store answers on the `minio` alias with the same
`MINIO_*` settings), but **neither reads the old volumes**. Plan both steps before
you pull the new version.

### Upgrade scripts

`scripts/upgrade/0.1.0/` automates the risky parts. Copy the directory next to
(not into) your install and run each script with `--dir <install dir>`; `--help`
documents every option. None of them prints a secret or deletes a volume.

| Script | When | What it does |
|---|---|---|
| `preflight.sh` | Before anything, on the running old stack. Read-only. | PASS/WARN/FAIL table: secrets against the 0.1.0 boot rules, `REDIS_PASSWORD`/`REDIS_URL` consistency, `WIDGET_EMBED_BASE_URL`/`PUBLIC_WEB_URL` on the Caddy origin, plain-number port variables, ports 80/443 free, disk space for the copy and backups, the running Qdrant version (0.1.0 pins 1.20.0; Qdrant cannot downgrade or skip a minor version), the cached MinIO image, and the stream backlog. Exits 1 on any FAIL. `--no-docker` checks only `.env`. |
| `drain-queues.sh` | Right before stopping the old stack. | Stops the producers (caddy, web, edge, control-plane, scheduler-worker), waits until every consumer group has nothing pending or undelivered, then stops the workers. `--dry-run` only reports, `--skip-eval` does not wait for evaluation scores, `--timeout` bounds the wait. |
| `migrate-objectstore.sh` | After `up -d postgres redis qdrant objectstore` on 0.1.0, before the app services. | Starts a temporary MinIO from the image cached on the host on the old volume, `rclone copy`s the bucket into SeaweedFS (never deletes, resumable), and verifies count, total size, per-object sizes and a downloaded checksum sample. `--dry-run` writes nothing. |

The order is: back up → `preflight.sh` → fix FAILs → `drain-queues.sh` →
`$C down` → update the code → build → start the datastores →
`migrate-objectstore.sh` → start `embeddings control-plane` (every pending
migration runs here: 0024–0030 on a pre-0.1.0 install) → start everything. The sections below explain each step.

Also check before switching:

- `WEB_PORT`, `CONTROL_PLANE_PORT` and `EDGE_HOST_PORT` must be plain port
  numbers. 0.1.0 already binds web, edge and the control plane to `127.0.0.1`,
  so a value like `127.0.0.1:3000` produces an invalid mapping.
- Caddy (`caddy` service) now owns ports 80/443. Stop any reverse proxy on the
  host, and set `WIDGET_EMBED_BASE_URL` to the Caddy origin (`http://<host>`, or
  `https://<RAGGIE_DOMAIN>`); embed snippets that still point at `:8080` stop
  working and must be redistributed.
- Qdrant moves to 1.20.0. Qdrant cannot downgrade its storage, and a
  single-node Qdrant cannot skip a minor version: it must run the latest patch
  of every minor in between. `preflight.sh` checks both.
  - Already on 1.19.x or 1.20.0 (for example a former `qdrant/qdrant:latest`):
    nothing to do.
  - Older than 1.19: on the old stack, run `qdrant/qdrant:v1.19.2` on the same
    volume first (and `v1.18.3` before it if you are below 1.18), wait until
    `/readyz` answers, then upgrade.
  - Newer than 1.20.0: pin the compose file to the version you run.

### Valkey: drain the workers first

Valkey 8 cannot load the RDB/AOF files Redis 7.4 writes, so it starts on a fresh
`valkey_data` volume and leaves `redis_data` untouched. Rate-limit counters,
login lockouts, idempotency keys and the query cache start empty, which is
harmless. Events that were still queued are lost, so:

1. Stop new uploads and wait until no document is *Pending* or *Processing* in
   the knowledge base and recent answers have their evaluation scores
   (`scripts/upgrade/0.1.0/drain-queues.sh` does this and stops the workers).
2. Upgrade (below). Anything that was still in flight is picked up again by
   the stale-document sweep once it has been stuck for `STALE_PENDING_SECONDS`
   (default 15 minutes); to do it sooner use *Retry failed* in the knowledge
   base, or `POST /api/v1/admin/documents/reindex-all` as a platform admin.
3. Once the new stack has run for a while, remove the old volume yourself
   (`docker volume rm raggie_redis_data`); Raggie never deletes it.

### SeaweedFS: copy the files before switching

The new `objectstore` service stores data in `objectstore_data`; the old
`minio_data` volume is not read. Copy the bucket across **before** the
application services start against the new store, otherwise documents keep
their search chunks but lose their original files (download and re-processing
fail).

1. **On the old version**, with MinIO still running, copy the bucket out with
   `mc mirror` or `rclone sync` ([backup-restore.md](backup-restore.md#backup)).
2. Stop the stack: `$C down` (never `down -v`).
3. Check out 0.1.0 and build: `$C --profile core build`.
4. Start only the datastores:
   `$C --profile core up -d postgres redis qdrant objectstore`.
5. Copy the files in with `scripts/upgrade/0.1.0/migrate-objectstore.sh`, which
   reads the old `minio_data` volume directly and verifies the copy. To do it by
   hand instead: `rclone sync /backup raggie:raggie-uploads` (or `mc mb` then
   `mc mirror`, as in the restore steps), then compare the object counts of the
   backup and the new bucket (`rclone size`). With the script, step 1 is only a
   safety backup: the old volume is never modified.
6. Start everything: `$C --profile core up -d`.

Your existing `.env` keeps working: `MINIO_ENDPOINT=minio:9000` resolves to the
new store, and `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` become its S3
credentials. `MINIO_CONSOLE_PORT` is no longer used (SeaweedFS has no MinIO
console) and can be deleted. If you would rather keep an S3 service you run
yourself (MinIO, Ceph RGW, AWS S3, ...), point `MINIO_ENDPOINT` and the
credentials at it under a hostname other than `minio`, and skip the copy. When
the files are verified, remove `raggie_minio_data` yourself.

### Edge needs `DATABASE_URL` in production

Outside `RAGGIE_ENV=development` the edge now refuses to start without
`DATABASE_URL`, because it reads chat authorization from Postgres.
`.env.example` and `install.sh` set it and compose passes `.env` to the edge;
check deployments that configure the edge some other way.

## How migrations work

- SQL files live in `services/control-plane/migrations/` as
  `NNNN_name.up.sql` (with a matching `.down.sql` for reference).
- `raggie_control_plane/db/migrate.py` applies the `.up.sql` files in order, each
  in its own transaction, and records them in `schema_migrations`.
- A session-level advisory lock makes concurrent runs safe; already-applied
  migrations are skipped, so re-running is harmless.
- `RUN_MIGRATIONS_ON_BOOT` (default `true`) runs them at control-plane start-up.
  Set it to `false` when a separate job runs migrations.

## Rolling back

There is no automated down-migration. To roll back:

1. Stop the stack.
2. Restore the Postgres backup taken before the upgrade (and the files bucket, if
   documents were uploaded since).
3. Check out the previous version and start it.

The `.down.sql` files document how each change could be reversed by hand; review
them carefully before running any of them against real data.

## Changing the embedding model

Switching the embedding provider or model changes the vector space and requires
re-embedding your documents; the control plane detects the mismatch and, by
default, pauses new uploads until you re-embed. See
[embeddings.md](embeddings.md#changing-models-and-re-embedding).
