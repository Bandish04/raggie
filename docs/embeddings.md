# Embeddings and reranking

Raggie turns documents and questions into vectors through one internal service,
`embeddings`. The edge (search) and the ingestion workers (indexing) always talk
to this gateway; nothing else calls an embedding model. Qdrant, the vector
database, always runs on your server.

> **Status for 0.1.0.** **Local mode is the default.** Cloud mode (an
> OpenAI-compatible embedding API and/or a remote reranker behind the same
> gateway) is opt-in and **experimental**: the gateway, the installer presets
> (`install.sh --embeddings cloud`) and the admin card are implemented and
> unit-tested, but no run against a live provider has validated it end to end.

- [Local mode (default)](#local-mode-default)
- [Cloud mode](#cloud-mode)
- [Reranker options](#reranker-options)
- [Changing models and re-embedding](#changing-models-and-re-embedding)
- [Sizing and throughput](#sizing-and-throughput)
- [Privacy](#privacy)

## How it works

Every chunk gets two vectors:

- **Dense** (semantic) from the embedding model, 1024 dimensions by default.
- **Sparse** (lexical, BM25 via `Qdrant/bm25`), always computed **locally**, in
  both modes.

At query time the edge searches both and fuses the results with Reciprocal Rank
Fusion (`RETRIEVE_CANDIDATE_K=80` candidates), then a cross-encoder **reranker**
reorders the top `RERANK_CANDIDATE_K` (12 as shipped in `.env.example`; 24 when
unset), and the best `RETRIEVE_CONTEXT_K=12`
chunks (at most 3 per document, softly) go into the prompt. If the reranker fails
or times out, the fused order is kept (fail-open). Set `SPARSE_ENABLED=false` to
fall back to dense-only search.

## Local mode (default)

| Role | Model | License |
|---|---|---|
| Dense | `intfloat/multilingual-e5-large` (1024-d, Turkish + English) | MIT |
| Sparse | `Qdrant/bm25` | Apache-2.0 |
| Reranker | `Alibaba-NLP/gte-multilingual-reranker-base` (int8 ONNX) | Apache-2.0 |

All three run on CPU through ONNX Runtime; no GPU is needed. The models are baked
into the image at build time (`EMBEDDINGS_BAKE=dense,sparse,rerank`), so a running
stack does not download anything. Plan for about **3–4 GB of RAM** for the service
(the dense model needs ~2.2 GB; the reranker's working set is bounded by
`RERANKER_BATCH_SIZE`).

Document text and questions never leave the server in local mode.

### Image variants and offline mode

The gateway runs with `HF_HUB_OFFLINE=1` and a read-only model cache: it never
downloads models at runtime, and a model that is not in the image is a startup
error (`ModelNotAvailable`), not a silent download.

| Image | Contains | Use for |
|---|---|---|
| `-local` | dense, BM25 and reranker models (`EMBEDDINGS_BAKE=dense,sparse,rerank`) | **local mode** (the default) |
| `-slim` | only the BM25 model (`EMBEDDINGS_BAKE=sparse`) | cloud mode with a cloud reranker (or `RERANKER_PROVIDER=none`) |

`EMBEDDINGS_PROVIDER=local` (or `RERANKER_PROVIDER=local`) on the `-slim` image
fails at boot with `ModelNotAvailable`. Use `-local` for local mode. Setting
`HF_HUB_OFFLINE=0` with a writable volume at `FASTEMBED_CACHE_PATH` makes the
gateway download the pinned models on first start instead, but this is
discouraged: the first boot then depends on Hugging Face being reachable, and
the downloaded files are not covered by the image you tested.

Images only ever contain the default models in [MODELS.md](../MODELS.md). The
bake step ignores `RERANKER_MODEL` and the other model variables, and refuses
any non-default model. To run an opt-in local model such as
`BAAI/bge-reranker-v2-m3`, set `RERANKER_MODEL` together with the
download-on-first-start setup above. You then download that model yourself and
are responsible for its license: `jinaai/jina-reranker-v2-base-multilingual`
is non-commercial (CC-BY-NC-4.0).

## Cloud mode

Cloud mode sends **dense** embedding requests (and optionally reranking) to an
external provider, which makes the stack lighter (no 2 GB model in RAM) at the
cost of sending document text and questions to that provider. BM25 sparse vectors
stay local, so hybrid search keeps working.

```dotenv
EMBEDDINGS_PROVIDER=openai_compatible
EMBEDDINGS_UPSTREAM_BASE_URL=https://api.openai.com/v1   # the gateway POSTs {base}/embeddings
EMBEDDINGS_MODEL=text-embedding-3-large                   # the provider's versioned model id
EMBEDDING_DIM=1024
EMBEDDINGS_REQUEST_EXTRA_JSON={"dimensions":1024}
EMBEDDINGS_BAKE=sparse                                    # smaller image: only the BM25 model
```

Upstream API keys go in **`.env.embeddings`** (file mode 600), which compose passes
only to the `embeddings` service, never in the shared `.env`. In cloud mode the
gateway requires callers to authenticate with `INTERNAL_API_SECRET`, so set it on
the edge, the workers and the gateway.

Provider-specific fields are merged into requests with
`EMBEDDINGS_REQUEST_EXTRA_JSON` (all requests), `EMBEDDINGS_QUERY_EXTRA_JSON` and
`EMBEDDINGS_PASSAGE_EXTRA_JSON` (asymmetric models), for example
`{"input_type":"query"}` / `{"input_type":"document"}` (Voyage, Cohere-style) or
`{"task":"retrieval.query"}` (Jina). Query/passage prefixes are automatic: e5
models get `query: ` / `passage: ` locally, cloud models get none; override with
`EMBEDDINGS_QUERY_PREFIX` / `EMBEDDINGS_PASSAGE_PREFIX`.

Known-good starting points (model ids and dimensions should be verified against
your provider's current documentation):

| Provider | `EMBEDDINGS_MODEL` | Extra JSON |
|---|---|---|
| OpenAI | `text-embedding-3-large` | `{"dimensions":1024}` |
| Jina | `jina-embeddings-v3` | query `{"task":"retrieval.query"}`, passage `{"task":"retrieval.passage"}` |
| Voyage | a `voyage-3.5` / multilingual model | query `{"input_type":"query"}`, passage `{"input_type":"document"}` |
| Mistral | `mistral-embed` | — |
| Self-hosted (TEI, vLLM, Ollama) | your served model | as needed |

Behaviour of upstream calls:

| Call | Timeout | Retries |
|---|---|---|
| Query embedding (search) | `EMBEDDINGS_QUERY_TIMEOUT_SECONDS=3` | `EMBEDDINGS_QUERY_RETRIES=1` |
| Passage embedding (ingest) | `EMBEDDINGS_PASSAGE_TIMEOUT_SECONDS=60` | `EMBEDDINGS_PASSAGE_RETRIES=5`, full-jitter back-off, honours `Retry-After` |
| Remote rerank | `RERANKER_TIMEOUT_SECONDS=3` | none (search falls back to the fused order) |

Each gateway replica uses `EMBEDDINGS_UPSTREAM_CONCURRENCY=8` upstream slots, two
of them reserved for search queries so bulk ingestion cannot block chat. Batches
are capped at 64 texts or 200,000 characters; inputs are truncated to
`EMBEDDINGS_MAX_INPUT_CHARS=8000`. Repeated questions are served from a Valkey
cache (`EMBEDDINGS_CACHE_TTL_SECONDS=86400`, keyed by model fingerprint and a hash
of the question).

The gateway probes the upstream at start-up and every
`EMBEDDINGS_PROBE_INTERVAL_SECONDS`; if the returned vector length does not match
`EMBEDDING_DIM`, it reports not-ready with the reason.

## Reranker options

| `RERANKER_PROVIDER` | Notes |
|---|---|
| `local` (default) | `RERANKER_MODEL`, default `Alibaba-NLP/gte-multilingual-reranker-base`. `BAAI/bge-reranker-v2-m3` (Apache-2.0) is higher quality but about 2× slower on CPU. `jinaai/jina-reranker-v2-base-multilingual` is **CC-BY-NC (non-commercial)**: do not use it for commercial deployments. |
| `cohere`, `voyage`, `tei` | Remote rerank API at `RERANKER_UPSTREAM_URL`; key in `.env.embeddings`. Sends the question and the candidate passages. |
| `none` | No reranking (same as `RERANKER_ENABLED=false`). |

A popular combination is **cloud dense + local rerank**, since remote reranking is
often the larger recurring cost. Changing only the reranker never requires
re-embedding.

## Changing models and re-embedding

Vectors from different models are not comparable, so each embedding profile
(provider, model, dimension, prefixes, extra JSON; URLs and keys are excluded) has
a **fingerprint** and its own Qdrant collection:

- the default local e5 profile uses `raggie_chunks_d1024`;
- any other profile uses `raggie_chunks_d{dim}_{fingerprint}`.

Two models with the same dimension therefore never share a collection. Rotating an
API key does not change the fingerprint.

When the gateway's fingerprint differs from the one your documents were embedded
with, the control plane follows `EMBEDDINGS_FINGERPRINT_POLICY`:

| Policy | Behaviour |
|---|---|
| `block_ingest` (default) | The app stays up, new uploads are refused, and admins are told to re-embed. |
| `refuse_boot` | The control plane will not start until the mismatch is resolved. |
| `auto_reindex` | Re-embeds automatically, but only if `EMBEDDINGS_REEMBED_CONFIRM` is set to the **new** fingerprint (a deliberate confirmation). |

Re-embedding writes into the new collection; the old collection is left in place
until you delete it, so you can roll back by switching the profile back. Documents
not yet re-embedded are not searchable under the new profile, so plan a
maintenance window for large corpora. Zero-downtime migration between profiles is
planned for a later release.

## Sizing and throughput

Embedding is CPU-bound. Total concurrent embeds should be roughly the core count;
over-parallelising makes ingestion slower and can fail documents. On an 8-core
host a stable configuration is 2 `embeddings` replicas × `EMBEDDINGS_ONNX_THREADS=4` and 2
`ingestion-worker` replicas × `INGEST_MAX_CONCURRENCY=2`:

```bash
docker compose -f deploy/compose/docker-compose.yml --env-file .env --profile core \
  up -d --scale embeddings=2 --scale ingestion-worker=2
```

Ingest and retrieval latency figures will be published with the benchmark reports
([methodology](benchmarks/README.md); no results yet).

## Privacy

| Mode | Leaves the server |
|---|---|
| Local | Nothing. |
| Cloud dense | Document chunks (at ingest) and user questions (at search) go to `EMBEDDINGS_UPSTREAM_BASE_URL`. |
| Remote rerank | Each question plus up to `RERANK_CANDIDATE_K` candidate passages go to `RERANKER_UPSTREAM_URL`. |

Under KVKK/GDPR a cloud provider is a data processor: you need a legal basis and a
data processing agreement for the transfer. See [data-handling.md](data-handling.md).
