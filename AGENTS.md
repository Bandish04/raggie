# AGENTS.md

Guidance for AI coding agents (and humans) working in this repository.
Read [CONTRIBUTING.md](CONTRIBUTING.md) first; this file adds the
repository-specific rules that agents tend to miss.

## What Raggie is

A self-hosted RAG + AI chat platform: upload documents, get a cited internal
assistant and an embeddable support widget. Multi-tenant
(Organization → Team (nested) → Workspace), TR/EN.

## Services

| Service | Tech | Path | Port |
|---|---|---|---|
| edge (chat / RAG / SSE / widget) | Go 1.26 | `services/edge` | 8080 (metrics: 9090, internal) |
| control-plane (admin API, RBAC/ABAC, owns DB migrations) | Python 3.13, FastAPI | `services/control-plane` | 8000 (loopback only) |
| workers (ingestion / eval / scheduler, one image, `WORKER_ROLE`) | Python 3.13 | `services/workers` | 9100 (health) |
| embeddings gateway (dense + BM25 sparse + reranker; local or cloud) | Python, fastembed | `services/embeddings` | 8002 (internal) |
| web (admin + internal chat) | Next.js App Router, TypeScript | `web` | 3000 |
| widget (embeddable, Shadow DOM) | vanilla JS | `widget` | served by edge |

Datastores: PostgreSQL (schema owned only by control-plane migrations),
Qdrant (named vectors `dense` + `bm25`, RRF hybrid), Valkey (Redis-compatible:
rate limits, idempotency, Streams event bus; compose service `redis`),
S3-compatible object storage (SeaweedFS bundled as `objectstore`, alias `minio`).

## Commands

```bash
make setup          # interactive setup wizard for this checkout (same as install.sh)
make env            # create .env from .env.example (development defaults)
make up-core        # single-node stack (needs an LLM endpoint in .env)
make up-demo        # core stack + deterministic mock LLM, no API key
make up-ollama      # core stack + bundled Ollama (qwen3:4b-instruct), no API key
make test           # backend suites, no Docker: datastore tests SKIP (FAIL under CI=true)
make test-integration  # starts disposable Postgres/Valkey/Qdrant, then runs every suite
make test-installer    # installer/configure script tests (plain bash, fake curl)
make lint
make migrate        # idempotent, safe with multiple replicas
cd services/edge && go test ./...
cd web && pnpm lint && pnpm exec tsc --noEmit && pnpm test:unit && pnpm i18n:check
```

## Rules that CI enforces or reviewers will reject

- **Security first.** Every new HTTP route needs an entry in the authorization
  matrix (`services/control-plane/tests/security/authz_policy.yaml`,
  `services/edge/internal/httpserver/authz_matrix_test.go`); CI fails otherwise.
  Resources from another organization must look missing (404).
- **Tenant isolation.** Every query is scoped to the caller's org/workspace.
  Document queries filter `deleted_at IS NULL` (and `archived_at IS NULL` where
  "live" documents are meant).
- **The widget never reaches admin APIs.** Widget tokens use `aud=widget`, are
  origin-checked, and never get MCP tools.
- **Configuration.** Every new env knob gets a default in code and a commented
  entry in `.env.example`. No new required secrets. Outside
  `RAGGIE_ENV=development`, services refuse to start with default or weak secrets.
- **Features are double-gated:** a global env kill switch plus a per-workspace
  toggle in the database (web search, personalization, MCP, ...).
- **i18n.** `web/messages/en.json` and `tr.json` must have identical key paths
  (`pnpm i18n:check`). User-facing text never hard-codes a language.
- **Migrations** are plain SQL pairs in `services/control-plane/migrations`
  (`NNNN_name.up.sql` / `.down.sql`), idempotent where possible.
- **Tests first** for bug fixes: a failing regression test, then the fix.
- **Commits:** `type(scope): short summary`, a blank line, then a body that
  explains why. Sign off every commit (`git commit -s`, DCO).
- **Never commit** secrets, real customer data, `.env`, or files under
  `internal/`.
