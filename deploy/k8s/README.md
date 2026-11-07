# Kubernetes manifests (reference, community preview)

Plain Kustomize manifests for running Raggie on Kubernetes:

- `base/`: namespace, shared ConfigMap, datastores (PostgreSQL, Qdrant, Valkey,
  SeaweedFS S3), app workloads, ingress, PDBs and NetworkPolicies. **The base
  contains no secrets.** Every pod meets the Pod Security `restricted` profile
  (non-root, read-only root filesystem, no capabilities, RuntimeDefault seccomp)
  and sets CPU/memory requests and limits.
- `overlays/dev`: single replicas, development mode. It generates throwaway
  development secrets from `overlays/dev/secrets.dev.env`.
- `overlays/prod`: multiple replicas, pinned registry images, autoscaling,
  observability and TLS on both Ingresses. **You provide the `raggie-secrets`
  Secret.**

Validate the overlays with `make kustomize-validate` (it also runs
`deploy/k8s/tests/tls_test.sh`, which checks the TLS settings below offline).

## TLS (prod overlay)

The base and the dev overlay serve plain HTTP. The prod overlay terminates TLS
on both Ingresses with [cert-manager](https://cert-manager.io/), as the Helm
chart does.

Prerequisites:

- ingress-nginx (the SSE annotations below target it; set the equivalents for
  another controller);
- cert-manager installed in the cluster;
- a `ClusterIssuer`. The overlay uses one named `letsencrypt`; to use another
  name, change the `cert-manager.io/cluster-issuer` annotations in
  `overlays/prod/ingress-tls.yaml`.

With an HTTP-01 issuer, cert-manager starts a short-lived solver pod in the
`raggie` namespace. The base `default-deny-ingress` policy would isolate that
pod, so `overlays/prod/acme-networkpolicy.yaml` admits the `ingress-nginx`
namespace to the solver port (8089) only. DNS-01 issuers don't need it.

Set your hostnames in `overlays/prod/config-tls.yaml`, and nowhere else:

| Key | Surface | Example |
|---|---|---|
| `PUBLIC_WEB_URL` | admin + internal chat (web) | `https://ai.example.com` |
| `WIDGET_EMBED_BASE_URL` | public chat / widget (edge) | `https://help.example.com` |

Both values are origins only (`https://<host>`, with no path, port or trailing
slash). Kustomize `replacements` copy each host into its Ingress rule and TLS
entry, so certificates, the CSRF origin check and the widget snippet always
agree. cert-manager stores the certificates in the `raggie-admin-tls` and
`raggie-public-tls` Secrets.

The same patch sets `COOKIE_SECURE=true` and `ENABLE_HSTS=true`. Both need the
site to be reachable over HTTPS: login cookies are not sent over plain HTTP, and
browsers keep enforcing HSTS after it is turned off. If you terminate TLS
somewhere else (a cloud load balancer, a service mesh), remove the `tls` blocks
and the issuer annotations, but keep these settings and the https URLs.

For SSE, the public Ingress disables proxy buffering in both directions and
allows 3600 s reads and sends. The admin Ingress, where the web app proxies the
internal chat stream, disables response buffering and allows 3600 s reads.

## Production secrets

Every service refuses to start with default, placeholder (`change-me…`) or short
(<32 byte) secrets unless `RAGGIE_ENV=development`. Create the Secret before you
apply the prod overlay:

```bash
kubectl create namespace raggie
kubectl -n raggie create secret generic raggie-secrets \
  --from-literal=POSTGRES_PASSWORD="$(openssl rand -hex 24)" \
  --from-literal=MINIO_ROOT_USER=raggie \
  --from-literal=MINIO_ROOT_PASSWORD="$(openssl rand -hex 24)" \
  --from-literal=JWT_SECRET="$(openssl rand -hex 32)" \
  --from-literal=WIDGET_TOKEN_SECRET="$(openssl rand -hex 32)" \
  --from-literal=INTERNAL_API_SECRET="$(openssl rand -hex 32)" \
  --from-literal=SETUP_TOKEN="$(openssl rand -hex 32)" \
  --from-literal=LLMAAS_API_KEY="<your LLM provider key>"
# MINIO_ROOT_USER / MINIO_ROOT_PASSWORD are the S3 credentials of the bundled
# SeaweedFS object store (or of your own S3 endpoint, see MINIO_ENDPOINT).
# Optional: add QDRANT_API_KEY (>= 32 bytes, e.g. openssl rand -hex 32) to
# enable Qdrant auth; every service sends it automatically.
# Optional: add REDIS_PASSWORD to enable Valkey auth, and then also set
# REDIS_URL=redis://:<password>@redis:6379/0 in this Secret (it overrides the
# ConfigMap value).
# DATABASE_URL must embed the same Postgres password:
kubectl -n raggie patch secret raggie-secrets --type merge -p \
  "{\"stringData\":{\"DATABASE_URL\":\"postgresql://raggie:$(kubectl -n raggie get secret raggie-secrets -o jsonpath='{.data.POSTGRES_PASSWORD}' | base64 -d)@postgres:5432/raggie\"}}"

kubectl apply -k deploy/k8s/overlays/prod
```

In GitOps setups, manage the same keys with
[External Secrets](https://external-secrets.io/) or
[Sealed Secrets](https://github.com/bitnami-labs/sealed-secrets) instead of
`kubectl create`.

Read `SETUP_TOKEN` back when you create the first admin at `/onboarding`.

## High availability

A Helm chart with `single` and `ha` profiles is planned (operator-managed
PostgreSQL, Valkey Sentinel, distributed Qdrant, external S3). Until then these
manifests run the datastores as single replicas, which suits evaluation but not
production HA.

The object store is SeaweedFS (Apache-2.0) in single-node mode. Any other
S3-compatible service works: point `MINIO_ENDPOINT` (ConfigMap) and the
`MINIO_ROOT_*` credentials (Secret) at it and drop the `objectstore` StatefulSet.
