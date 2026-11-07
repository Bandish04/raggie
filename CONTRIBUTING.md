# Contributing to Raggie

Thanks for helping! Raggie is a community-preview project. Small, focused,
well-tested pull requests are the fastest way to get a change merged.

- Questions and ideas: [GitHub Discussions](https://github.com/alicangunduz/raggie/discussions)
- Bugs and feature requests: [issues](https://github.com/alicangunduz/raggie/issues)
- **Security problems: never open a public issue — see [SECURITY.md](SECURITY.md).**
- Everyone taking part follows the [Code of Conduct](CODE_OF_CONDUCT.md).

## Developer Certificate of Origin (DCO)

Every commit must be signed off. By signing off you confirm the
[Developer Certificate of Origin 1.1](https://developercertificate.org/):
you wrote the change, or otherwise have the right to submit it under the
project's license (Apache-2.0). Contributions are licensed to the project and its
users under that same license (Apache-2.0, section 5); there is no separate
contributor license agreement.

```bash
git commit -s -m "fix(edge): reject empty workspace id"
```

This adds a `Signed-off-by: Your Name <you@example.com>` line. Use your real
name, and the same e-mail as the commit author: the `DCO` check on every pull
request ([`dco.yml`](.github/workflows/dco.yml)) requires it on each commit
(merge commits and Dependabot are exempt). To sign off commits you already
made: `git rebase --signoff main`.

## Prerequisites

- Docker with the Compose plugin (only for running the stack and the
  datastore-backed tests)
- Go 1.26 (an older Go downloads 1.26 by itself: `GOTOOLCHAIN=auto` is the default)
- Python 3.13 and [uv](https://docs.astral.sh/uv/)
- Node 22 and pnpm 9 (`corepack enable` picks the pinned version)

Install the web dependencies once:

```bash
(cd web && pnpm install --frozen-lockfile)
```

The Python Make targets use each service's `.venv`; when one is missing they
run through `uv run --frozen --extra dev --python 3.13`, which creates it from
`uv.lock` on first use. To create them up front:

```bash
for s in control-plane workers embeddings; do (cd services/$s && uv sync --frozen --extra dev --python 3.13); done
```

## Run the stack locally

```bash
make env       # creates .env from .env.example if it does not exist
make up-core   # Postgres, Valkey, Qdrant, SeaweedFS, edge, control plane, workers, embeddings, web, Caddy
```

Open <http://localhost/onboarding> (Caddy on port 80, or `HTTP_PORT`) to create
the first admin. The web app (`127.0.0.1:3000`) and the edge (`127.0.0.1:8080`)
are also published on loopback for debugging.

To work without any LLM API key, use the deterministic mock LLM instead of
`make up-core`:

```bash
make up-demo   # core stack + mock LLM (deploy/compose/docker-compose.demo.yml)
```

The mock answers every question with citations to the retrieved sources, which
is enough to exercise retrieval, streaming and the UI.

To try the installer's flow on your checkout (secrets, embeddings and LLM
questions, the same options as `install.sh`), run it in place with
`make setup ARGS="--yes --llm mock"`. When you change the installer or the
`deploy/scripts/configure-*.sh` helpers, run `make test-installer` (plain bash
with a fake `curl`, no Docker).

Other useful targets: `make logs`, `make ps`, `make down`, `make demo` (seeds a
synthetic demo company and the sample corpus). Run `make` to list all targets.

## Tests and checks

Run the checks for the parts you changed before opening a pull request.

| Area | Command |
|---|---|
| Backend tests (edge, control plane, workers, embeddings); no Docker | `make test` |
| The same plus the datastore-backed tests (starts Postgres/Valkey/Qdrant in Docker) | `make test-integration` |
| Disposable Postgres/Valkey/Qdrant for tests | `make test-deps-up` / `make test-deps-down` |
| Installer scripts (plain bash, no Docker) | `make test-installer` |
| Lint (go vet, ruff check + format check, web ESLint) | `make lint` |
| Format Python (pinned ruff; CI fails on unformatted code) | `make format` |
| Go fuzz targets (short run) | `make fuzz-short` |
| Go fuzz targets (long run, nightly) | `make fuzz-long` |
| Kubernetes manifests | `make kustomize-validate` |
| Web | `cd web && pnpm lint && pnpm exec tsc --noEmit && pnpm test:unit && pnpm i18n:check && pnpm build` |
| Chat UI characterization (Playwright, stub backend, after `pnpm build`) | `cd web && pnpm test:chat` |
| Full-stack e2e (Playwright) | `eval "$(scripts/e2e-stack.sh up)"`, then `cd web && pnpm e2e:stack`; tear down with `scripts/e2e-stack.sh down` |
| Extra settings for the e2e stack (benchmarks) | `E2E_ENV_<KEY>=value` (for example `E2E_ENV_RATE_LIMIT_ENABLED=false`) or `E2E_EXTRA_ENV_FILE=path` with `KEY=VALUE` lines, set before `scripts/e2e-stack.sh up` |

`make test` does not start Docker. Tests that need a datastore carry a
`requires_postgres`, `requires_redis` or `requires_qdrant` marker and are
**skipped with a reason** unless the disposable datastores are up; under
`CI=true` they **fail** instead, so CI never passes by skipping them. To run
them locally:

- `make test-integration` starts the datastores (`make test-deps-up`) and runs
  every suite; or
- run `make test-deps-up` once, then `make test` (or a single suite) as often as
  you like. It writes the connection URLs (`TEST_DATABASE_URL`,
  `TEST_REDIS_URL`, `TEST_QDRANT_URL`) to `.test-deps.env`, which the make
  targets read and which you can source before running `pytest` by hand.
  `make test-deps-down` removes the containers.

The S3 object-store tests (`requires_s3`) are opt-in everywhere, CI included:
set `OBJECTSTORE_TEST_ENDPOINT` to an S3 endpoint to run them. To run only one
group, select by marker, for example `pytest -m requires_postgres` or
`pytest -m "not requires_qdrant"`.

`make fuzz-short` runs each Go fuzz target for 10 seconds, which fits a pull
request. `make fuzz-long` runs each target for 10 minutes and is what the
nightly workflow uses. Set `FUZZTIME` (for example `FUZZTIME=2m make fuzz-short`)
to override either duration.

Visual regression baselines (`web/e2e/visual-audit.spec.ts`) are per platform
and recorded on Linux only. Without a baseline for your platform the screenshot
checks skip with a hint, so do not commit macOS or Windows PNGs. To (re)record
them, a maintainer runs the **Visual baselines** workflow (Actions → Visual
baselines → Run workflow), downloads the `visual-baselines-linux` artifact,
copies the PNGs into `web/e2e/visual-audit.spec.ts-snapshots/` and commits them.

The README screenshots and the hero clip in `docs/assets/` come from the real
UI against the chat stub with the synthetic demo data
(`web/e2e/chat/readme-fixtures.mjs`). After a UI change, regenerate them with
`cd web && pnpm build && pnpm capture:readme`. It writes the PNGs and
`hero.webm`, plus `hero.mp4` and `hero.gif` when `ffmpeg` is installed. Use
only demo-seed names and the sample corpus in these visuals, never real people
or customers.

### Test-only environment variables

These variables only change how tests run. The services never read them.

| Variable | Default | Effect |
|---|---|---|
| `A2_LATENCY_BUDGET_MS` | `200` | p95 budget, in milliseconds, for the live edge retrieval latency check in `services/edge/internal/rag`. Raise it on slow or shared machines instead of editing the test. Values that are not positive integers fall back to 200. |
| `RAGGIE_SKIP_LATENCY_TESTS=1` | unset | Skips the wall-clock latency assertions. They are also skipped automatically under the Go race detector. |
| `RAGGIE_SLOW_TESTS=1` | unset | Enables the long Hypothesis/fuzz variants, for example `cd services/workers && RAGGIE_SLOW_TESTS=1 pytest -m slow tests/test_parsing_fuzz.py`. The nightly workflow sets it. |
| `EMBEDDINGS_MODEL_TESTS=1` | unset | Runs the `services/embeddings` tests marked `model` against the real ONNX models. The first run downloads the models, which takes a while and needs network access. |

## Project rules

These are enforced by tests or review. Pull requests that break them are not
merged.

### Every HTTP route needs an authorization policy

- **Edge (Go):** add the route to the policy table in
  `services/edge/internal/httpserver/authz_matrix_test.go`.
- **Control plane (FastAPI):** add an entry to
  `services/control-plane/tests/security/authz_policy.yaml`.

The authorization matrix tests fail when a route has no policy, or when a
policy names a route that no longer exists. They also check that every
principal you did not allow is refused.

### Web API routes are same-origin only

Every mutating route handler under `web/app/api/**` (POST, PUT, PATCH, DELETE)
must be wrapped in `withSameOrigin` from `web/lib/security/origin.ts`. A unit
test fails when one is not.

### i18n: Turkish and English, always together

- Never hard-code user-visible strings in components. Add every key to **both**
  `web/messages/en.json` and `web/messages/tr.json`.
- Use ICU plurals for anything with a count (`{count, plural, one {# file} other {# files}}`),
  never a fixed "(s)".
- `pnpm i18n:check` must pass: no duplicate keys, identical key paths in both
  files.

### Configuration knobs

- Every new environment variable goes into `.env.example` with a short comment
  and a safe default. Do not add new **required** secrets.
- Regenerate the configuration reference afterwards:

  ```bash
  make config-docs
  ```

  and commit the updated `docs/configuration.md`.

### Database migrations

- Migrations are SQL file pairs in `services/control-plane/migrations`:
  `NNNN_name.up.sql` plus a required, matching `NNNN_name.down.sql`, numbered
  after the latest one. Only the `.up.sql` files are applied; production
  upgrades are forward-only (roll back by restoring a backup, see
  [docs/upgrade.md](docs/upgrade.md#rolling-back)). The `.down.sql` documents
  how to undo the change and is applied by hand for local rollback.
- They are applied in order by `raggie_control_plane/db/migrate.py`, at control
  plane start-up or with `make migrate`. Each file runs in its own transaction,
  under an advisory lock, so several replicas can start at once.
- Never edit a migration that has already been released; add a new one.
- Document queries must respect soft delete (`deleted_at IS NULL`).

### Keep claims honest

Do not add performance, scale or compliance claims to the README or docs
without a reproducible benchmark or code that backs them.

## Commit style

```
type(scope): short summary in the imperative

Why the change is needed and what it does. Mention trade-offs and anything
reviewers should look at. End with what you ran, e.g.
"go test ./... green; pnpm lint/tsc/test:unit/i18n:check green".

Signed-off-by: Your Name <you@example.com>
```

Types: `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `build`, `ci`,
`chore`, `security`. Scopes are usually the service or area (`edge`,
`control-plane`, `workers`, `embeddings`, `web`, `widget`, `deploy`, `docs`).

## Pull requests

- One logical change per pull request. Link the issue it fixes.
- Fill in the pull request template checklist.
- Add or update tests: a bug fix starts with a failing test.
- Update the docs when behaviour, setup or configuration changes.
- Include screenshots for UI changes (both TR and EN if text changed).
- Never commit secrets, real customer data or `.env` files.

## Good first contributions

Look for issues labelled `good first issue` or `help wanted`. Documentation,
tests, translations and benchmark scripts are always welcome.
