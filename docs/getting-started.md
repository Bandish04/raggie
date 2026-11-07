# Getting started

This guide takes you from nothing to a cited answer on your own machine, then
points you to the production path.

- [1. Try it locally (no API keys)](#1-try-it-locally-no-api-keys)
- [2. Real answers: bundled Ollama or your own LLM](#2-real-answers-bundled-ollama-or-your-own-llm)
- [3. First steps in the app](#3-first-steps-in-the-app)
- [4. Embed the widget](#4-embed-the-widget)
- [5. Install on a server](#5-install-on-a-server)
- [Troubleshooting](#troubleshooting)

## Requirements

- Docker Engine 24+ with the Compose plugin (`docker compose version`).
- 8 GB RAM free for the default stack (the local embedding models alone use
  about 3–4 GB). See the [hardware table](../README.md#hardware).
- About 15 GB of disk for images and models, plus space for your documents.
- `make` and `git` for the source workflow.

## 1. Try it locally (no API keys)

`make up-demo` starts the `core` stack plus a deterministic, OpenAI-compatible
mock LLM that answers from the retrieved sources with `[n]` citations, and points
every LLM consumer at it (`deploy/compose/docker-compose.demo.yml`). Everything
else (search, ingestion, embeddings, the admin console) is the real thing.

```bash
git clone https://github.com/alicangunduz/raggie && cd raggie
make env       # creates .env from .env.example (development defaults)
make up-demo   # core stack + mock LLM, no API key needed
```

The first build compiles the services and bakes the embedding models into the
`embeddings` image, so it takes a while. Follow progress with `make logs`; the
web container reports healthy once the UI is up.

Everything is served through the bundled **Caddy** front door on port 80. If
something else already uses port 80, set `HTTP_PORT=8081` (for example) in `.env`
and use `http://localhost:8081` below. The web app's own port `3000` is only
published on `127.0.0.1` for debugging.

Then:

1. Open <http://localhost/onboarding>.
2. Create the first administrator (passwords need at least 12 characters). In
   development mode no setup token is required.
3. The wizard creates your first workspace and offers to upload documents.

Optional: `make demo` seeds a synthetic company ("Nebula Teknoloji") with
10 departments, 25 users and the 39 sample documents from
`examples/sample-corpus/`. The demo users' passwords are printed once.

> `make env` copies `.env.example`, which sets `RAGGIE_ENV=development`. That
> disables the production secret checks and is only meant for local evaluation.
> Never expose a development stack to a network.

## 2. Real answers: bundled Ollama or your own LLM

**Still no API key:** run Ollama inside the stack.

```bash
make up-ollama       # core stack + Ollama with qwen3:4b-instruct (CPU)
make up-ollama-gpu   # the same with NVIDIA GPU passthrough
```

The default model, `qwen3:4b-instruct` (Apache-2.0, about 2.5 GB), handles
Turkish and English and answers at a usable speed on a CPU-only host. The first
start pulls it, so it takes a few minutes; no data leaves the host. Pick another
model with `OLLAMA_MODEL` (for example `qwen3:8b` on a GPU).

**Your own endpoint:** Raggie talks to any OpenAI-compatible `/v1` chat endpoint.
Edit `.env`:

```dotenv
LLMAAS_BASE_URL=https://api.openai.com/v1      # or your vLLM / Ollama / gateway URL
LLMAAS_API_KEY=sk-...
LLMAAS_CHAT_MODEL=gpt-4o-mini                  # the model id your endpoint expects
```

Apply with `make up-core`: it recreates the services without the demo or Ollama
overlay, so they read the LLM settings from `.env` again. For Ollama, vLLM and
multi-model routing see [llm-providers.md](llm-providers.md).

## 3. First steps in the app

- **Upload documents:** *Admin → Knowledge base*. PDF, DOCX, XLSX, PPTX, TXT and
  MD are parsed; scanned PDFs and images go through OCR (Turkish + English).
  Status moves from *Pending* to *Processing* to *Ready*; failed documents show
  the reason and are retried automatically.
- **Ask questions:** open *Chat*, pick the workspace, ask. Answers stream with
  numbered citations; open *Sources* to see the passages used.
- **Invite people:** *Admin → Team* creates invite links (no email server
  needed). Roles: *Staff* (chat), *Workspace admin* (manage workspaces they
  belong to), *Super admin* (manage the organization).
- **Review quality:** *Admin → Flagged* lists answers whose faithfulness or
  citation scores fell below the thresholds.
- **Switch language:** the UI is available in Turkish and English (account
  menu). Answers follow the language of the question.

## 4. Embed the widget

1. Create a workspace of type **External** (the onboarding wizard offers
   "Customer Support Widget", or use *Admin → Workspaces*).
2. Allow the website origin(s) that may embed it: in *Admin → Workspaces*,
   click the **Widget sites** button on the External workspace's row, add each
   origin and press **Save**. Origins are exact `scheme://host[:port]` values
   (`https://www.example.com` and `https://example.com` are different origins);
   paths and wildcards are rejected. Until at least one origin is saved, the
   widget loads nowhere.
3. Paste the embed snippet before `</body>` (the onboarding wizard shows it for
   an External workspace; it is simply):

   ```html
   <script src="https://chat.example.com/widgets/embed.js?id=WORKSPACE_ID"></script>
   ```

   The script origin is your Caddy front door: `http://localhost` locally, or
   `https://<RAGGIE_DOMAIN>` on a server (set `WIDGET_EMBED_BASE_URL` to the same
   value so the onboarding wizard prints the right snippet).

The widget renders in a Shadow DOM, talks only to the widget paths of the front
door, and can only reach the workspace it was issued for. See
[security-model.md](security-model.md#3-trust-boundaries-stride) for the details.

## 5. Install on a server

For a Linux server with Docker, the installer downloads a pinned,
sha256-verified release into `/opt/raggie`, generates strong secrets, sets
`RAGGIE_ENV=production`, starts the stack (published images, Caddy as the only
public entry point) and prints the one-time setup token:

```bash
curl -fsSL https://github.com/alicangunduz/raggie/releases/latest/download/install.sh | sudo bash -s -- \
  --domain chat.example.com --acme-email ops@example.com \
  --llm ollama
```

To verify the installer before running it, download it with the release's
checksum file:

```bash
curl -fsSLO https://github.com/alicangunduz/raggie/releases/latest/download/install.sh
curl -fsSLO https://github.com/alicangunduz/raggie/releases/latest/download/SHA256SUMS
sha256sum -c --ignore-missing SHA256SUMS
sudo bash install.sh --domain chat.example.com
```

The main options (all of them: `bash install.sh --help`):

| Option | Meaning |
|---|---|
| `--llm mock\|ollama\|self-hosted\|openai` | `mock` = offline demo; `ollama` = bundled Ollama; `self-hosted` = your vLLM/Ollama URL; `openai` = an OpenAI-compatible provider (`--llm-base-url`, `--llm-api-key`, `--llm-model`). Asked interactively, the suggestion is `ollama` on hosts with at least 12 GB RAM, otherwise `mock`; with `--yes` the default is `mock`. |
| `--ollama-model ID`, `--gpu auto\|yes\|no` | Model for the bundled Ollama (default `qwen3:4b-instruct`) and NVIDIA GPU use (`auto` = when `nvidia-smi` works). |
| `--embeddings local\|cloud` | Where document text is embedded; cloud mode also needs `--accept-data-transfer` with `--yes`. |
| `--domain HOST`, `--acme-email ADDR` | HTTPS with an automatic Let's Encrypt certificate; DNS must point at the server and ports 80/443 must be reachable. |
| `--http-port N`, `--https-port N` | Front-door ports (default 80 and 443). |
| `--public-url URL` | Public origin, when another proxy or CDN sits in front of Caddy. |
| `--yes` | Never prompt: flags, `RAGGIE_*` environment variables, then defaults. |

Every flag can also be given as an environment variable (`--llm-api-key` →
`RAGGIE_LLM_API_KEY`), which keeps keys out of your shell history. Re-running the
installer upgrades the install: `.env` and `.env.embeddings` are backed up and
only gain new keys, never overwritten. `--ref main` installs a development
snapshot from a branch, which is **not** checksum-verified; do not use it in
production.

In a repository checkout, `make setup ARGS="--yes --llm mock"` runs the same
wizard in place.

Before going live, read [production.md](production.md) and check the firewall.

## Troubleshooting

| Symptom | Check |
|---|---|
| `onboarding` asks for a setup token | Production mode. Use the token printed by the installer, or find it in `docker compose logs control-plane` (printed once at first boot). |
| A service exits right after start with "refusing to start with insecure secrets" | `RAGGIE_ENV` is production and a secret is a default, placeholder or shorter than 32 bytes. Generate one with `openssl rand -hex 32`. |
| Documents stay *Pending* | `docker compose logs ingestion-worker embeddings`. The embeddings service must be healthy before ingestion starts. Documents stuck longer than `STALE_PENDING_SECONDS` (15 min) are re-queued automatically. An embeddings container that exits with `ModelNotAvailable` is the `-slim` image running local mode: use `-local`. |
| Answers say no relevant sources were found | The document may still be processing, or it is in a different workspace than the one selected in chat. |
| The widget shows "unavailable" | The page's origin is not in the workspace allow-list, or the workspace is not of type External. |
| Login is temporarily blocked | Five failed attempts lock the account with an increasing back-off (30 s up to 15 min). |
