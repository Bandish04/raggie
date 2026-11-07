# Clean-install matrix

Results come from the **Install smoke** workflow
([`.github/workflows/install-smoke.yml`](../../.github/workflows/install-smoke.yml)):
nightly, on demand, and on pull requests that touch the installer
(`web/public/install.sh`, `deploy/scripts/**`, `deploy/compose/**`). Each job
writes its numbers to the run's job summary; copy a release's run here.

## What each leg does

Driver: [`scripts/install-smoke.sh`](../../scripts/install-smoke.sh).

1. **Build** the images once (cache warm-up, reported separately, not part of A1).
2. **Fresh install**: `web/public/install.sh --source . --yes --llm mock --embeddings local`
   on a clean runner. **A1** = installer start → `/login` served through the
   Caddy front door and control-plane `/readyz` green (budget 45 s, images cached).
   The installer must print the setup token and the onboarding URL.
3. **First admin**: onboarding bootstrap with the generated `SETUP_TOKEN`, then a
   workspace.
4. **Golden question**: upload
   `examples/sample-corpus/kalite-yonetimi/Kalite_Metrikleri_2026_Q3.txt`, wait
   for `SUCCESS`, ask golden `kal-009` over `/api/v1/chat/stream` through the
   front door; the answer must end with `done`, carry ≥ 1 source including the
   expected document, and cite it (`[n]`). The mock LLM's wording is templated,
   so this checks retrieval and citation plumbing, not answer quality (that is
   the eval harness).
5. **Upgrade re-run**: the installer again; `.env` must be byte-identical except
   for a block of appended keys, and the stack must stay healthy.

On failure the job uploads `compose ps`/`logs` and the installer output (setup
token masked); the stack is always torn down.

## Matrix

| Runner | Embeddings | LLM | Notes |
|---|---|---|---|
| ubuntu-22.04 (amd64) | local | mock | |
| ubuntu-24.04 (amd64) | local | mock | |
| ubuntu-24.04-arm (arm64) | local | mock | |
| ubuntu-24.04 (amd64) | cloud (`custom` preset → offline mock upstream) | mock | no secrets: exercises consent, live probe, `-slim` image, key isolation |

Real cloud providers (OpenAI, Jina, Voyage, Mistral) and the bundled Ollama
are not in the matrix: the former need API keys, the latter a ~2.5 GB model
pull per run.

## Results

| Date | Commit | Runner | Embeddings | Image build | Installer | A1 | Ingest | Golden | Upgrade |
|---|---|---|---|---|---|---|---|---|---|
| _pending first run_ | | | | | | | | | |
