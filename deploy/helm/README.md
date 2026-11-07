# Helm chart: `raggie`

`deploy/helm/raggie` installs the whole platform: edge, control-plane, web,
the ingestion, eval and scheduler workers, the embeddings gateway, and their
datastores. It comes with two profiles.

| | `values-single.yaml` | `values-ha.yaml` |
|---|---|---|
| Use | dev, demo, evaluation | production, no in-cluster single point of failure |
| App replicas | 1 | ≥ 2 (edge 3); zone + host spread, PDBs, HPA for edge and embeddings |
| PostgreSQL | in-chart StatefulSet (1) | CloudNativePG `Cluster`: 3 instances, quorum sync replication, Barman WAL + daily backup to S3 |
| Valkey | in-chart standalone (1) | 3 × (valkey + sentinel), StatefulSet, `min-replicas-to-write 1` |
| Qdrant | in-chart single node | official `qdrant/qdrant` chart (dependency), 3 nodes, distributed mode |
| Object storage | in-chart SeaweedFS (1) | external S3 (recommended) |
| Secrets | generated throwaway Secret | your `existingSecret` (required) |

Both profiles share the same hardening: Pod Security `restricted` (non-root,
read-only root filesystem with an `emptyDir` `/tmp`, all capabilities dropped,
`RuntimeDefault` seccomp), no service-account token, default-deny
NetworkPolicies with explicit allow-lists, and readiness/liveness/startup
probes on `/readyz` and `/healthz`.

## Single profile

```bash
helm repo add qdrant https://qdrant.github.io/qdrant-helm
helm dependency build deploy/helm/raggie
helm install raggie deploy/helm/raggie -n raggie --create-namespace \
  -f deploy/helm/raggie/values-single.yaml
kubectl -n raggie port-forward svc/raggie-web 3000:3000
```

Read the setup token for `/onboarding` with
`kubectl -n raggie get secret raggie-dev-secrets -o jsonpath='{.data.SETUP_TOKEN}' | base64 -d`.
The dev Secret is kept on `helm uninstall` (`helm.sh/resource-policy: keep`) so
a reinstall still opens the old database volume.

## HA profile

### 1. Operators and cluster add-ons

| Component | Why | Install |
|---|---|---|
| [CloudNativePG](https://cloudnative-pg.io) ≥ 1.26 | renders `Cluster`, `ScheduledBackup`, `Pooler` | `kubectl apply --server-side -f https://github.com/cloudnative-pg/cloudnative-pg/releases/download/v1.30.1/cnpg-1.30.1.yaml` |
| [Barman Cloud Plugin](https://cloudnative-pg.io/plugin-barman-cloud/) | `postgresql.cnpg.backup.method=plugin` (default) | needs cert-manager; `kubectl apply -f https://github.com/cloudnative-pg/plugin-barman-cloud/releases/download/v0.15.1/manifest.yaml` |
| [cert-manager](https://cert-manager.io) | TLS for the Ingresses (`ingress.clusterIssuer`) and the Barman plugin | upstream chart |
| An Ingress controller | the two Ingresses (public chat/widget host, admin host) | defaults target ingress-nginx annotations; set `ingress.className` and the per-host `annotations` for yours |
| [KEDA](https://keda.sh) (optional) | `keda.enabled`: edge on in-flight SSE streams, workers on stream lag | upstream chart |
| metrics-server | the CPU HPAs | usually preinstalled |

`postgresql.cnpg.backup.method=barmanObjectStore` uses CNPG's in-tree Barman
support instead of the plugin; CNPG deprecated it, so prefer the plugin.

The ingress-nginx project is retired upstream; the chart only depends on the
annotations you pass. Whatever the controller, keep response buffering off
and the read timeout long on the public host: chat answers are Server-Sent
Events.

### 2. Secrets

The chart never renders secret values in the `ha` profile. Create these
before installing (or manage the same keys with External Secrets / Sealed
Secrets):

```bash
kubectl create namespace raggie

# App secret: env name == key. Required: JWT_SECRET, WIDGET_TOKEN_SECRET,
# INTERNAL_API_SECRET (>= 32 bytes). REDIS_PASSWORD when valkey.auth=true;
# QDRANT_API_KEY because values-ha.yaml enables the Qdrant API key.
kubectl -n raggie create secret generic raggie-secrets \
  --from-literal=JWT_SECRET="$(openssl rand -hex 32)" \
  --from-literal=WIDGET_TOKEN_SECRET="$(openssl rand -hex 32)" \
  --from-literal=INTERNAL_API_SECRET="$(openssl rand -hex 32)" \
  --from-literal=SETUP_TOKEN="$(openssl rand -hex 32)" \
  --from-literal=METRICS_TOKEN="$(openssl rand -hex 32)" \
  --from-literal=QDRANT_API_KEY="$(openssl rand -hex 32)" \
  --from-literal=REDIS_PASSWORD="$(openssl rand -hex 24)" \
  --from-literal=LLMAAS_API_KEY="<your LLM provider key>"

# Object storage used by control-plane and the workers (s3.existingSecret).
kubectl -n raggie create secret generic raggie-s3 \
  --from-literal=accessKey=<access key> --from-literal=secretKey=<secret key>

# Barman backups (postgresql.cnpg.backup.s3CredentialsSecret).
kubectl -n raggie create secret generic raggie-backup-s3 \
  --from-literal=ACCESS_KEY_ID=<access key> --from-literal=ACCESS_SECRET_KEY=<secret key>

# Optional, cloud embeddings only. Mounted ONLY into the embeddings pods.
kubectl -n raggie create secret generic raggie-embeddings \
  --from-literal=EMBEDDINGS_UPSTREAM_API_KEY=<key> \
  --from-literal=RERANKER_UPSTREAM_API_KEY=<key>
```

The PostgreSQL password comes from the `<release>-pg-app` Secret that CNPG
creates. Passwords are spliced into `DATABASE_URL` / `REDIS_URL` with
Kubernetes `$(VAR)` expansion, so use URL-safe values (hex as above).

Optional app keys, all read only when present: `INTEGRATION_ENC_KEY`,
`OIDC_CLIENT_SECRET`, `SCIM_BEARER_TOKEN`, `BRAVE_API_KEY`.

The Qdrant subchart reads `QDRANT_API_KEY` from `raggie-secrets` with Helm's
`lookup` at render time. GitOps tools that render without cluster access
(Argo CD) do not support `lookup`; give the subchart its own key Secret there.

### 3. Install

```bash
helm repo add qdrant https://qdrant.github.io/qdrant-helm
helm dependency build deploy/helm/raggie
helm install raggie deploy/helm/raggie -n raggie -f deploy/helm/raggie/values-ha.yaml \
  --set s3.external.endpoint=s3.eu-central-1.amazonaws.com \
  --set ingress.public.host=chat.example.com --set ingress.admin.host=admin.example.com \
  --set config.publicWebUrl=https://admin.example.com \
  --set config.widgetEmbedBaseUrl=https://chat.example.com \
  --set config.llm.baseUrl=https://llm.example.com/v1
```

Render-time guards reject unsafe `ha` combinations (generated secrets,
in-chart PostgreSQL, standalone Valkey, single Qdrant, a Sentinel set under 3,
an edge grace period shorter than its drain budget).

## Configuration reference

| Values | Env | Notes |
|---|---|---|
| `config.*` | `RAGGIE_ENV`, `DEFAULT_LOCALE`, `DEFAULT_TIMEZONE`, `LLMAAS_*`, `RETRIEVE_*`, `RERANK_*`, ... | shared ConfigMap, `envFrom` in every app container |
| `config.extraEnv` | any | extra non-secret env for every app container |
| `<component>.env` | any | per component |
| `embeddingsGateway.provider` | `EMBEDDINGS_PROVIDER` (`local` \| `openai_compatible`) | cloud mode needs `upstreamBaseUrl`; the embeddings image tag defaults to `<version>-local` or `<version>-slim` to match |
| — | `INTERNAL_API_SECRET` | from `secrets.existingSecret` into edge, control-plane, every worker and embeddings: callers send it as a Bearer token and the gateway requires it in cloud mode |
| `edge.embedQueryTimeoutMs`, `edge.rerankTimeoutMs` | `EMBED_QUERY_TIMEOUT_MS` (8000), `RERANK_TIMEOUT_MS` (5000) | edge → embeddings budgets; rerank fails open |
| `embeddingsGateway.rerankerProvider` | `RERANKER_PROVIDER` (`local` \| `cohere` \| `voyage` \| `tei` \| `none`) | `rerankerUpstreamUrl` for remote rerankers |
| `embeddingsGateway.existingSecret` | `EMBEDDINGS_UPSTREAM_API_KEY`, `RERANKER_UPSTREAM_API_KEY` | separate Secret, embeddings pods only |
| `edge.shutdown.*` | `EDGE_SHUTDOWN_DELAY_SECONDS` (5), `EDGE_SHUTDOWN_DRAIN_SECONDS` (25), `EDGE_TERMINATION_GRACE_SECONDS` (35) | pod `terminationGracePeriodSeconds` = 35 |
| `edge.metricsPort` | `METRICS_ADDR=":9090"` | exposed on the edge Service as `metrics` |
| `migrations.enabled` | control-plane `RUN_MIGRATIONS_ON_BOOT=false` | see Migrations |
| `valkey.mode=sentinel` | `REDIS_SENTINEL_ADDRS`, `REDIS_SENTINEL_MASTER`, `REDIS_SENTINEL_PASSWORD` | set for every service |
| `vectordb.replicationFactor`, `.shardNumber`, `.writeConsistencyFactor` | `QDRANT_REPLICATION_FACTOR`, `QDRANT_SHARD_NUMBER`, `QDRANT_WRITE_CONSISTENCY_FACTOR` | applied by the workers when a collection is first created |
| `embeddings.onnxThreads` | `EMBEDDINGS_ONNX_THREADS` | empty = 4, capped at `embeddings.resources.limits.cpu` |
| `embeddings.cacheTimeoutSeconds` | `EMBEDDINGS_CACHE_TIMEOUT_SECONDS` (0.5) | per Redis call of the query cache |
| `workers.embedTimeoutSeconds`, `workers.embedMaxRetries` | `EMBED_TIMEOUT_SECONDS` (180), `EMBED_MAX_RETRIES` (6) | worker → embeddings passage batches |
| `config.retrieval.rerankCandidateK` | `RERANK_CANDIDATE_K` (12) | sized for CPU rerankers; raise for GPU/cloud |
| `s3.*` | `MINIO_ENDPOINT`, `MINIO_BUCKET`, `MINIO_USE_SSL`, `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD` | S3 client env contract |
| `networkPolicy.egress.*` | — | CIDR allow-lists for LLM, cloud embeddings, S3, OIDC, edge web search |

## Migrations

`python -m raggie_control_plane.db.migrate` applies the bundled SQL under a
PostgreSQL advisory lock; control-plane runs with `RUN_MIGRATIONS_ON_BOOT=false`
and its `/readyz` stays 503 while the schema is behind the code.

- `helm upgrade`: a `pre-upgrade` hook Job migrates before any pod rolls.
  Migrations must stay backward compatible with the previous release
  (expand → deploy → contract).
- First `helm install` with `postgresql.mode=cnpg` or `internal`: the database
  is part of the release and does not exist at `pre-install` time, so the Job
  (`<release>-migrate-install`) is a regular resource that waits for the
  database. control-plane turns Ready when it finishes; `helm install --wait`
  converges on its own.
- `postgresql.mode=external`: the hook also runs `pre-install`.

## NetworkPolicies

Install into a dedicated namespace: the chart's default-deny applies to every
pod in it. Allowed paths, besides DNS:

- ingress controller → web, edge (public paths); web → edge, control-plane.
- control-plane accepts traffic only from web: the public edge has no route
  to the admin API (A4).
- scheduler → edge (internal task endpoint); edge, control-plane, workers →
  embeddings; app pods → their datastores only.
- datastore peers (CNPG replication + operator, Sentinel, Qdrant Raft/p2p).
- external egress only from `networkPolicy.egress.*` CIDRs. NetworkPolicy
  cannot match hostnames; use an FQDN-capable CNI policy (Cilium, Calico) for
  provider hostnames.

## Scaling signals

| Component | Default | With KEDA |
|---|---|---|
| edge | HPA on CPU (+ `edge.hpa.extraMetrics`, e.g. `raggie_edge_active_streams` via prometheus-adapter) | `prometheus` trigger on `sum(raggie_edge_active_streams)` + CPU |
| embeddings | HPA on CPU | — |
| ingestion / eval workers | fixed replicas | `redis-streams` / `redis-sentinel-streams` lag of `ingestion-workers` / `eval-workers` |
| scheduler | fixed (2 in ha; `FOR UPDATE SKIP LOCKED` keeps runs single) | — |

## Known gaps

- Replication/shard settings apply only when a collection is created.
  Collections created earlier (e.g. under the single profile) keep one
  replica; replicate their shards once through the Qdrant cluster API
  (`scripts/ha/chaos.sh` shows how).
- Valkey replication is asynchronous; see `docs/benchmarks/ha-chaos.md` for
  the event-loss window and what closes it.
- Qdrant snapshots to S3 are not scheduled by the chart.

## Validation and chaos testing

```bash
scripts/ha/validate-chart.sh   # helm lint/template, kubeconform (k8s 1.30 + CRD catalog), kube-linter, guards
scripts/ha/up.sh               # kind (3 workers) + CNPG + the ha profile with offline LLM/embeddings
scripts/ha/chaos.sh            # the six failure drills; results in docs/benchmarks/ha-chaos.md
scripts/ha/down.sh
```

`validate-chart.sh` needs native `helm`, `kubeconform` and `kube-linter` (on
PATH or in the Go bin dir) and fails with the install command when one is
missing:

```bash
go install github.com/yannh/kubeconform/cmd/kubeconform@v0.7.0
go install golang.stackrox.io/kube-linter/cmd/kube-linter@v0.8.3
```

`files/widget/embed.js` is a copy of `widget/embed.js` (Helm reads files only
from inside the chart); `scripts/ha/sync-widget.sh` refreshes it and
`validate-chart.sh` fails on drift.
