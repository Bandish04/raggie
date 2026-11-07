# Raggie — root developer task runner.
# Usage: `make` (or `make help`) to list targets. `##@ Title` lines are the
# help sections; a `## text` after a target is its help line.

# --env-file pins interpolation to the repo-root .env (compose otherwise looks
# beside the compose file). env_file: ../../.env in the file uses the same source,
# so ${VAR} interpolation and container env stay consistent.
COMPOSE      := docker compose -f deploy/compose/docker-compose.yml --env-file .env
K8S_OVERLAYS := deploy/k8s/overlays/dev deploy/k8s/overlays/prod

# $(call PYTOOL,tool, args): run a Python dev tool from the service's .venv, or,
# on a fresh clone without one, through uv (which creates it from uv.lock).
PYTOOL = if [ -x ./.venv/bin/$(1) ]; then ./.venv/bin/$(1)$(2); \
	elif command -v uv >/dev/null 2>&1; then uv run --frozen --extra dev --python 3.13 $(1)$(2); \
	else echo "$(1): no .venv and no uv. Install uv (https://docs.astral.sh/uv/), see CONTRIBUTING.md"; exit 127; fi

# Same ruff as CI (RUFF_VERSION in ci.yml) for the trees without a lockfile
# (scripts/, tests/security/); their ruff.toml enforces it via required-version.
RUFF_VERSION := 0.15.15

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show this help
	@echo "Raggie — available targets:"
	@awk 'BEGIN {FS = ":.*?## "} \
		/^##@/ {printf "\n\033[1m%s\033[0m\n", substr($$0, 5); next} \
		/^[a-zA-Z0-9_-]+:.*?## / {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# Guard for targets that talk to an existing stack: a clear hint instead of
# compose's "couldn't find env file". Not listed in help.
.PHONY: need-env
need-env:
	@test -f .env || { echo "No .env here. Run 'make env' (local dev) or 'make setup' (installer wizard) first."; exit 1; }

##@ Setup

.PHONY: env
env: ## Create .env from .env.example if missing
	@test -f .env || (cp .env.example .env && echo "Created .env from .env.example — edit it before running make up-core.")

.PHONY: setup
setup: ## Setup wizard for this checkout (same as install.sh), e.g. make setup ARGS="--yes --llm mock"
	bash web/public/install.sh --source . $(ARGS)

.PHONY: migrate
migrate: need-env ## Apply database migrations (idempotent; safe with multiple replicas)
	$(COMPOSE) run --rm control-plane python -m raggie_control_plane.db.migrate

.PHONY: demo
demo: need-env ## Seed the synthetic demo company + sample corpus into the running stack
	$(COMPOSE) run --rm -v "$(CURDIR)/examples/sample-corpus:/corpus:ro" control-plane \
		python -m raggie_control_plane.demo seed --corpus /corpus

##@ Run the stack

.PHONY: up-core
up-core: env ## Bring up the single-node `core` stack (needs an LLM endpoint in .env)
	$(COMPOSE) --profile core up -d

.PHONY: up-demo
up-demo: env ## Zero-key demo: `core` stack + deterministic mock LLM (no API key, no GPU)
	$(COMPOSE) -f deploy/compose/docker-compose.demo.yml --profile core --profile mock up -d

.PHONY: up-ollama
up-ollama: env ## `core` stack + bundled Ollama (local LLM, no API key; first start pulls the model)
	$(COMPOSE) -f deploy/compose/docker-compose.ollama.yml --profile core up -d

.PHONY: up-ollama-gpu
up-ollama-gpu: env ## Same as up-ollama with NVIDIA GPU passthrough for Ollama
	$(COMPOSE) -f deploy/compose/docker-compose.ollama.yml -f deploy/compose/docker-compose.gpu.yml --profile core up -d

.PHONY: pull
pull: need-env ## Pre-pull the third-party images (app images are built locally)
	$(COMPOSE) --profile core pull

.PHONY: ps
ps: need-env ## Show running services
	$(COMPOSE) ps

.PHONY: logs
logs: need-env ## Tail logs of the local stack
	$(COMPOSE) logs -f --tail=100

.PHONY: down
down: need-env ## Stop and remove the local stack
	$(COMPOSE) down

##@ Develop & test

.PHONY: build
build: build-edge build-control-plane build-workers build-web ## Build all services

.PHONY: build-edge
build-edge: ## Build the Go chat/RAG edge
	cd services/edge && go build ./...

.PHONY: build-control-plane
build-control-plane: ## Compile-check the FastAPI control plane
	cd services/control-plane && python3 -m compileall -q .

.PHONY: build-workers
build-workers: ## Compile-check the Python workers
	cd services/workers && python3 -m compileall -q .

.PHONY: build-web
build-web: ## Build the Next.js app
	cd web && CI=true pnpm install --frozen-lockfile && CI=true pnpm build

.PHONY: lint
lint: format-check ## Lint all services (includes the Python format check CI enforces)
	cd services/edge && go vet ./...
	cd services/control-plane && $(call PYTOOL,ruff, check .)
	cd services/workers && $(call PYTOOL,ruff, check .)
	cd services/embeddings && $(call PYTOOL,ruff, check .)
	cd web && CI=true pnpm lint

.PHONY: format format-check
format: ## Format all Python code with the pinned ruff
	cd services/control-plane && $(call PYTOOL,ruff, format .)
	cd services/workers && $(call PYTOOL,ruff, format .)
	cd services/embeddings && $(call PYTOOL,ruff, format .)
	uvx "ruff@$(RUFF_VERSION)" format scripts tests/security bench
format-check: ## Check Python formatting without changing files (the CI gate)
	cd services/control-plane && $(call PYTOOL,ruff, format --check .)
	cd services/workers && $(call PYTOOL,ruff, format --check .)
	cd services/embeddings && $(call PYTOOL,ruff, format --check .)
	uvx "ruff@$(RUFF_VERSION)" format --check scripts tests/security bench

.PHONY: test
test: test-edge test-control-plane test-workers test-embeddings ## Run all backend suites; infra tests SKIP unless test deps are up

.PHONY: test-integration
test-integration: test-deps-up ## Start disposable Postgres/Redis/Qdrant (Docker), then run all suites including infra tests
	$(MAKE) test

.PHONY: test-edge
test-edge: ## Run Go edge tests
	cd services/edge && go test ./...

# Test-dependency URLs come from .test-deps.env when `make test-deps-up` has run;
# without it, tests that need Postgres/Redis/Qdrant are skipped with a reason
# (and fail loudly under CI=true).
.PHONY: test-control-plane
test-control-plane: ## Run control-plane tests
	@if [ -f ./.test-deps.env ]; then . ./.test-deps.env; fi; cd services/control-plane && \
		if [ -n "$${TEST_DATABASE_URL:-}" ]; then export DATABASE_URL=$$TEST_DATABASE_URL; fi && \
		$(call PYTOOL,pytest, -q)

.PHONY: test-workers
test-workers: ## Run worker tests
	@if [ -f ./.test-deps.env ]; then . ./.test-deps.env; fi; cd services/workers && \
		if [ -n "$${TEST_DATABASE_URL:-}" ]; then export DATABASE_URL=$$TEST_DATABASE_URL REDIS_TEST_URL=$$TEST_REDIS_URL QDRANT_TEST_URL=$$TEST_QDRANT_URL; fi && \
		$(call PYTOOL,pytest, -q)

.PHONY: test-embeddings
test-embeddings: ## Run embeddings gateway tests (real-model tests need EMBEDDINGS_MODEL_TESTS=1)
	cd services/embeddings && $(call PYTOOL,pytest, -q)

.PHONY: test-installer
test-installer: ## Installer/configure script tests (plain bash, fake curl, no Docker)
	bash deploy/scripts/tests/run.sh

.PHONY: test-deps-up
test-deps-up: ## Bring up disposable Postgres/Redis/Qdrant for local tests
	./scripts/test_deps.sh up

.PHONY: test-deps-down
test-deps-down: ## Stop disposable local test dependencies
	./scripts/test_deps.sh down

.PHONY: test-deps-logs
test-deps-logs: ## Tail logs of the disposable local test dependencies
	./scripts/test_deps.sh logs

.PHONY: fuzz-short
fuzz-short: ## Run every Go fuzz target briefly (per-PR budget)
	cd services/edge && FUZZTIME=$${FUZZTIME:-10s} scripts/fuzz.sh

.PHONY: fuzz-long
fuzz-long: ## Run every Go fuzz target for 10 minutes each (nightly)
	cd services/edge && FUZZTIME=$${FUZZTIME:-10m} scripts/fuzz.sh

.PHONY: kustomize-validate
kustomize-validate: ## Validate all k8s overlays with `kubectl kustomize`
	@for o in $(K8S_OVERLAYS); do \
		echo "==> kubectl kustomize $$o"; \
		kubectl kustomize --load-restrictor LoadRestrictionsNone $$o > /dev/null && echo "    OK" || exit 1; \
	done
	@bash deploy/k8s/tests/tls_test.sh

##@ Benchmarks

.PHONY: bench-test
bench-test: ## Unit-test the benchmark/eval harnesses (no stack needed)
	cd bench && go vet ./... && go test -race ./...

.PHONY: bench-a2 bench-a3 bench-a5 eval
bench-a2: ## Benchmark retrieval latency (A2 gate) against a running stack (ARGS="-dry-run" for a fake)
	cd bench && go run ./a2-retrieval $(ARGS)
bench-a3: ## Benchmark 50-page PDF ingestion time (A3 gate) against a running stack
	cd bench && go run ./a3-ingest $(ARGS)
bench-a5: ## Benchmark concurrent chat streams (A5 gate) against a running stack
	cd bench && go run ./a5-sse $(ARGS)
eval: ## Retrieval-quality eval over the golden set against a running stack
	cd bench && go run ./eval $(ARGS)

.PHONY: eval-judge
eval-judge: ## Benchmark the faithfulness judge on the labeled set against LLMAAS_* (ARGS=--dry-run validates only)
	cd services/workers && $(call PYTOOL,python, ../../bench/judge_eval.py $(ARGS))

.PHONY: a1
a1: ## Measure compose-up to working login (A1 gate; RESTART=1 for a cold start)
	@bash deploy/probes/a1_time_to_login.sh

.PHONY: load-a5
load-a5: ## k6 chat load smoke test against the local edge (A5; needs k6, WS=, TOKEN=)
	@k6 run -e VUS=$${VUS:-200} -e DURATION=$${DURATION:-1m} \
		-e EDGE=$${EDGE:-http://localhost:8080} -e WS=$${WS} -e TOKEN=$${TOKEN} \
		deploy/load/a5_chat_load.js

##@ Release & maintenance

.PHONY: notices
notices: ## Regenerate THIRD_PARTY_NOTICES.md (needs go, uv, pnpm + network; run `pnpm install` in web/ first)
	python3 scripts/notices/gen_third_party.py

.PHONY: license-headers
license-headers: ## Add missing SPDX headers to first-party files (CI runs --check)
	python3 scripts/license/spdx.py

.PHONY: config-docs
config-docs: ## Regenerate docs/configuration.md from .env.example
	python3 scripts/gen-config-docs.py
