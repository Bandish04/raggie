# Production deployment

This page covers running Raggie on a single server with Docker Compose: TLS, the
firewall, secrets, sizing and monitoring. Kubernetes notes are at the end.

- [Checklist](#checklist)
- [Production mode and secrets](#production-mode-and-secrets)
- [Network layout](#network-layout)
- [HTTPS: the Caddy front door](#https-the-caddy-front-door)
- [Firewall: Docker bypasses UFW](#firewall-docker-bypasses-ufw)
- [Sizing and scaling](#sizing-and-scaling)
- [Monitoring](#monitoring)
- [Graceful restarts](#graceful-restarts)
- [Kubernetes](#kubernetes)

## Checklist

- [ ] `RAGGIE_ENV=production`, every secret generated (the installer does this).
- [ ] `RAGGIE_DOMAIN` set (automatic HTTPS from the bundled Caddy); ports 80
      and 443 reachable from the internet, nothing else but SSH.
- [ ] `COOKIE_SECURE` empty or `true`, `ENABLE_HSTS=true`, and
      `WIDGET_EMBED_BASE_URL` (and `PUBLIC_WEB_URL`, if set) on
      `https://<RAGGIE_DOMAIN>`.
- [ ] Backups scheduled and a restore tested ([backup-restore.md](backup-restore.md)).
- [ ] The embeddings image matches the mode: `-local` for local embeddings or a
      local reranker, `-slim` only for cloud embeddings with a cloud (or no)
      reranker. The gateway runs offline and does not download models
      ([embeddings.md](embeddings.md#image-variants-and-offline-mode)).
- [ ] Decide what may leave the server: LLM provider, cloud embeddings, web
      search, MCP ([data-handling.md](data-handling.md)).

## Production mode and secrets

Any `RAGGIE_ENV` other than `development`, `dev`, `local`, `test` or `testing`
(including unset) is **production**. In production the edge, control plane and
workers refuse to start if a secret is missing, a known default or placeholder
(`change-me…`), or too short:

| Secret | Minimum | Checked by |
|---|---|---|
| `JWT_SECRET`, `WIDGET_TOKEN_SECRET` | 32 bytes | edge, control plane |
| `INTERNAL_API_SECRET`, `METRICS_TOKEN` (when set) | 32 bytes | edge, workers / control plane |
| `INTEGRATION_ENC_KEY`, `SETUP_TOKEN`, `SCIM_BEARER_TOKEN` (when set) | 32 bytes | control plane |
| `POSTGRES_PASSWORD` (or the `DATABASE_URL` password), `MINIO_ROOT_PASSWORD` | 16 bytes | control plane, workers |
| `QDRANT_API_KEY`, `REDIS_URL` | not a known placeholder | control plane |

The edge also refuses to start in production without `DATABASE_URL`: it reads
chat authorization (workspace membership and type) from Postgres. In development
it starts without one, but chat and scheduled-task runs answer 503.

`.env.example` deliberately ships `RAGGIE_ENV=development` for local trials.
**Do not copy it to a server unchanged.** `install.sh` writes a production `.env`
with fresh secrets (`openssl rand -hex 32`) on first run and never overwrites an
existing one. To generate one by hand: `openssl rand -hex 32`.

Notes on rotating secrets:

- `JWT_SECRET` signs user sessions: rotating it signs everyone out.
- `WIDGET_TOKEN_SECRET` signs widget tokens: open widget sessions stop working
  until the visitor reloads the page.
- `INTEGRATION_ENC_KEY` encrypts stored integration credentials: rotating it
  makes them unreadable, so re-enter them afterwards.
- `SETUP_TOKEN` is only used for the very first admin; it is cleared once the
  first administrator exists.
- Keep `.env` (and `.env.embeddings` in cloud embedding mode) at file mode 600,
  owned by the deploying user, and out of version control.

## Network layout

Caddy is the single front door: it is the only service published on public
interfaces, and it serves the web app and the public edge paths from one origin.

| Service | Published by default | Reachable from |
|---|---|---|
| `caddy` (front door) | `0.0.0.0:80` and `:443` (`HTTP_PORT`, `HTTPS_PORT`) | the internet |
| `web` (Next.js) | `127.0.0.1:3000` (`WEB_PORT`) | Caddy; the loopback port is for debugging |
| `edge` (Go, widget + chat API) | `127.0.0.1:8080` (`EDGE_HOST_PORT`) | Caddy; the loopback port is for debugging |
| `control-plane` | `127.0.0.1:8000` | localhost (the web container talks to it over the compose network) |
| Postgres, Valkey (`redis`), Qdrant, object store (`objectstore`, S3 API on 9000) | `127.0.0.1` (`DATASTORE_BIND_HOST`) | localhost only |
| `embeddings`, `mockllm`, `ollama` | not published | compose network only |

Caddy routes `/widgets/*` (the widget loader), `/api/v1/widget/*` and
`/api/v1/chat/*` to the edge, refuses `/api/v1/internal/*` (404), and sends
everything else to the web app. The edge's own listen port is `EDGE_PORT`
(inside the container); `EDGE_HOST_PORT` is only the loopback publish.

## HTTPS: the Caddy front door

Set your domain in `.env` and point its DNS record at the server:

```dotenv
RAGGIE_DOMAIN=chat.example.com
ACME_EMAIL=ops@example.com        # optional: Let's Encrypt expiry notices
ENABLE_HSTS=true
WIDGET_EMBED_BASE_URL=https://chat.example.com
```

On the next `up`, Caddy obtains a Let's Encrypt certificate (ports 80 and 443
must be reachable from the internet), redirects HTTP to HTTPS and renews the
certificate on its own; certificates live in the `caddy_data` volume. Without
`RAGGIE_DOMAIN` it serves plain HTTP on `HTTP_PORT`, for local or LAN use only.

The configuration is `deploy/compose/caddy/Caddyfile`. Two properties matter
and are already handled there:

1. **`X-Forwarded-For` is overwritten** with the real client address, never
   appended to a client-supplied header, so per-IP rate limits and login limits
   cannot be dodged with a forged header. The edge trusts it from the compose
   network's private ranges (`TRUSTED_PROXY_CIDRS`).
2. **Server-sent events are not buffered:** answers stream token by token.

### Another proxy or CDN in front of Caddy

If a load balancer or CDN terminates TLS before Caddy, keep `RAGGIE_DOMAIN`
empty (Caddy then serves plain HTTP behind it), set `COOKIE_SECURE=true`, and add
the proxy's address ranges to the Caddyfile with the `trusted_proxies static
<cidr...>` server option. Otherwise Caddy discards the forwarded client address
and every visitor shares the proxy's IP for rate limiting.

## Firewall: Docker bypasses UFW

Ports published by Docker are opened through iptables rules that are evaluated
**before** UFW/firewalld rules, so `ufw deny` does not protect a port that Docker
publishes. With the default compose file only Caddy publishes public ports
(80/443); everything else is bound to `127.0.0.1`. Keep it that way: if you
change a publish to `0.0.0.0`, protect it with rules in the `DOCKER-USER` chain
(evaluated first) or a firewall in front of the machine (cloud security group).

Verify from another machine: `nmap -p 3000,8000,8080,5432,6379,6333,9000 your-server`
should show them closed or filtered; only 80/443 open.

## Sizing and scaling

Start from the [hardware table](../README.md#hardware) (estimates until benchmarks
are published). Knobs that matter:

| Concern | Knob |
|---|---|
| Concurrent chat streams per edge replica | `EDGE_MAX_SSE_CONNECTIONS` (default 12,500, `0` = unlimited; extra chats get a retryable 503 `busy` before any stream byte; watch `raggie_edge_sse_streams` and `raggie_edge_sse_streams_rejected_total`) |
| Load on the LLM provider | `LLMAAS_CHAT_MAX_CONCURRENCY` (64) per edge replica, `EVAL_MAX_CONCURRENCY` (4; 1 with bundled Ollama) per eval worker, or `max_concurrency` per provider in `LLM_MODEL_PROFILES_JSON` |
| Ingestion throughput (CPU-bound) | `embeddings` replicas × `EMBEDDINGS_ONNX_THREADS`, `ingestion-worker` replicas × `INGEST_MAX_CONCURRENCY`; keep the product near your core count ([embeddings.md](embeddings.md#sizing-and-throughput)) |
| Upload size | `MAX_UPLOAD_BYTES` (10 GiB), `UPLOAD_PART_SIZE` (16 MiB) |
| Parser safety | `PARSER_TIMEOUT_SECONDS`, `PARSER_MAX_PDF_PAGES` and the other `PARSER_*` limits |

## Monitoring

- Health: every service serves `/healthz` (process up) and `/readyz` (dependencies
  reachable). The web container's healthcheck uses `/healthz`.
- Metrics (Prometheus): the edge serves `/metrics` on a separate listener,
  `METRICS_ADDR=127.0.0.1:9090`, never on the public port. The control plane,
  embeddings and workers serve `/metrics` too. Set `METRICS_TOKEN` to require
  `Authorization: Bearer <token>`.
- Logs: every service logs to stdout (`docker compose logs <service>`). Prompts,
  answers and document text are not logged; see
  [data-handling.md](data-handling.md#5-logging).
- The Kubernetes production overlay ships an optional Prometheus, Loki, Tempo and
  Grafana stack (`deploy/k8s/observability`); the compose stack has none.

## Graceful restarts

On `SIGTERM` the edge stops accepting new chats (readiness fails), lets running
answers finish for `EDGE_SHUTDOWN_DRAIN_SECONDS` (25 s), then tells remaining
clients to reconnect. The web chat and the widget resume the interrupted answer
automatically. Keep `EDGE_SHUTDOWN_DRAIN_SECONDS + EDGE_SHUTDOWN_DELAY_SECONDS + 3`
below your stop timeout (Compose: `stop_grace_period`; Kubernetes:
`terminationGracePeriodSeconds`, mirrored in `EDGE_TERMINATION_GRACE_SECONDS`).

Database migrations run automatically when the control plane starts and are safe
with several replicas (advisory lock). See [upgrade.md](upgrade.md).

## Kubernetes

Two options ship in the repository, both labelled **community preview**:

- `deploy/helm/raggie`: a Helm chart with `values-single.yaml` and
  `values-ha.yaml`.
- `deploy/k8s`: Kustomize base plus `dev` and `prod` overlays (PodDisruptionBudgets,
  NetworkPolicies, autoscaling in prod). See [deploy/k8s/README.md](../deploy/k8s/README.md).

They have not yet been validated by chaos and disaster-recovery drills. Review
resource limits (the local embeddings service needs ~4 GiB), configure TLS on the
ingress, and provide secrets through your own secret manager.

### Client IPs behind an ingress that appends `X-Forwarded-For`

Unlike Caddy, most Kubernetes ingress controllers and cloud load balancers
**append** the client address to an incoming `X-Forwarded-For` instead of
replacing it. The edge reads that header from right to left and skips every hop
inside `TRUSTED_PROXY_CIDRS` (Helm: `config.trustedProxyCidrs`). The default
trusts all private ranges, so a client whose own address is private (office LAN,
VPN, another pod) counts as a proxy too, and the forged entries to its left
decide its rate-limit identity. Behind such an ingress, narrow the setting to
the ingress controller's pod or node range only, for example
`TRUSTED_PROXY_CIDRS=10.42.0.0/16` for the ingress pod CIDR. The control
plane reads the same variable with the same right-to-left rule (its default
also trusts loopback and every private range), so set it for both.
