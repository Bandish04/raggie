# HA chaos results

Failure drills for the Helm `ha` profile (`deploy/helm/raggie/values-ha.yaml`).
The [`HA chaos` workflow](../../.github/workflows/ha-chaos.yml) runs them weekly
(and on demand, optionally a subset) on a GitHub-hosted runner:
`scripts/ha/up.sh` → `scripts/ha/chaos.sh` → `scripts/ha/down.sh`. Each run
writes the results block below (failures and scenarios that did not run
included), the job summary, and uploads this file with the k6 logs and cluster
diagnostics as the `ha-chaos` artifact. The results quoted here come from such a
run; commit the file from the run you want to quote. The same scripts run on a
local kind cluster.

## Setup

| | |
|---|---|
| Cluster | kind `v0.30.0`, `kindest/node:v1.33.4` (digest-pinned in `scripts/ha/lib.sh`), 1 control plane + 3 workers in 3 fake zones (`scripts/ha/kind-config.yaml`) |
| Runner | `ubuntu-latest` (2-4 CPU, ~7 GB RAM) |
| Chart values | `values-ha.yaml` + `scripts/ha/values-kind.yaml` (replicas kept where a scenario needs them, small requests/limits, local images, edge drain 1 s) |
| PostgreSQL | CloudNativePG, 3 instances, quorum synchronous replication (`any 1`, `dataDurability: required`) |
| Valkey | 3 x (valkey + sentinel), quorum 2, `down-after-milliseconds` 3000 |
| Qdrant | official chart, 3 nodes; chunk collections get a second replica per shard |
| Object storage | single-node SeaweedFS (kind has no external S3) |
| LLM / embeddings | offline mock LLM (150 ms/token, ~5 s streams) and hashed bag-of-words mock embeddings |
| Load | in-cluster k6 driver (`scripts/ha/k6/chaos-load.js`, `grafana/k6:1.3.0`, digest-pinned): chat SSE, uploads, web + control-plane reads; a stream ended with `event: reconnect` is resumed with `resume_message_id` |

## Scenarios and pass criteria

| # | Fault | Pass criteria |
|---|---|---|
| 1 | Force-delete the PostgreSQL primary pod | New primary in < 30 s; every acknowledged chat turn is in `messages`; every acknowledged upload reaches `SUCCESS`. 5xx during the failover window are reported, not failed. |
| 2 | Force-delete the Valkey primary pod | Sentinel promotes a replica in < 30 s; every acknowledged upload (a `document.uploaded` event) reaches `SUCCESS`; after the old pod rejoins exactly one node reports `role:master`. |
| 3 | Force-delete one Qdrant node | Chat keeps answering: zero 5xx, zero connection errors, zero in-stream `event: error`. |
| 4 | Delete an edge pod mid-stream (graceful), then SIGKILL one | Graceful: at least one stream gets `event: reconnect` (the 1 s kind drain is shorter than a ~5 s stream) and every interrupted stream resumes with `resume_message_id` on the other replica to `event: done`; every acknowledged turn is in `messages`; zero 5xx, zero connection errors. SIGKILL: at most one broken stream per virtual user, zero 5xx, users recover on the next request. |
| 5 | SIGKILL every ingestion worker in turn during large uploads | Every acknowledged upload reaches `SUCCESS`, none `FAILED` (pending entries are reclaimed by a surviving or restarted consumer). |
| 6 | `helm upgrade` that rolls every app Deployment, under load | Zero 5xx, zero connection errors, zero stream errors, zero failed resumes; the `pre-upgrade` migration hook Job succeeded once with a single pod. |

Every scenario is a PASS/FAIL with its duration. Timing budgets:
`PG_FAILOVER_BUDGET` / `REDIS_FAILOVER_BUDGET` (30 s).

## Known gaps

- kind runs every node on one host: the drills cover pod and process failure,
  not real node, disk or network partitions.

- The workers create chunk collections with `QDRANT_REPLICATION_FACTOR` /
  `QDRANT_SHARD_NUMBER` / `QDRANT_WRITE_CONSISTENCY_FACTOR`. `chaos.sh` still
  tops up any shard with a single replica (collections created before those
  settings applied) through the Qdrant cluster API; it is a no-op otherwise.
- Valkey replication is asynchronous. `min-replicas-to-write 1` /
  `min-replicas-max-lag 10` bound the window, but an `XADD` acknowledged by a
  primary that dies before replicating it is lost. The scheduler's
  stale-document sweep re-publishes such a document after
  `STALE_PENDING_SECONDS` (default 900 s), but scenario 2 waits only
  `VERIFY_TIMEOUT` (300 s) and still reports it as a failure: the event was
  lost, even though the system recovers later.

## Results

<!-- results:begin -->
Not run yet: the first weekly `HA chaos` run (or a manual dispatch) fills this
block.
<!-- results:end -->
