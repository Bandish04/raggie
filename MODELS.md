# Models

Raggie's embeddings gateway (`services/embeddings`) runs the models below in
**local** mode. The `-local` container image bakes them in at the pinned
revisions; the `-slim` image contains only the BM25 model. In **cloud** mode,
dense embeddings and reranking come from the provider you configure, under that
provider's terms.

Licenses were checked against each model's Hugging Face metadata. Revisions are
pinned in `services/embeddings/raggie_embeddings/providers/models.py`.

| Role | Model (upstream) | Weights Raggie loads (pinned revision) | License | Default |
|---|---|---|---|---|
| Dense embeddings (1024-d, multilingual) | [`intfloat/multilingual-e5-large`](https://huggingface.co/intfloat/multilingual-e5-large) | `qdrant/multilingual-e5-large-onnx@ac6781cd` (ONNX export) | MIT | ✅ local |
| Sparse lexical (BM25) | [`Qdrant/bm25`](https://huggingface.co/Qdrant/bm25) | `Qdrant/bm25@22b8d2af` | Apache-2.0 | ✅ always |
| Reranker (cross-encoder) | [`Alibaba-NLP/gte-multilingual-reranker-base`](https://huggingface.co/Alibaba-NLP/gte-multilingual-reranker-base) | `onnx-community/gte-multilingual-reranker-base@ee64367e` (int8 ONNX) | Apache-2.0 | ✅ local |
| Reranker, higher quality, slower | [`BAAI/bge-reranker-v2-m3`](https://huggingface.co/BAAI/bge-reranker-v2-m3) | `onnx-community/bge-reranker-v2-m3-ONNX@6f5ff652` (int8 ONNX) | Apache-2.0 | opt-in |
| Reranker, legacy | [`jinaai/jina-reranker-v2-base-multilingual`](https://huggingface.co/jinaai/jina-reranker-v2-base-multilingual) | `@9cfeff2d` | **CC-BY-NC-4.0 (non-commercial)** | opt-in only; never baked into release images |

The ONNX exports are format conversions of the upstream weights and carry the
upstream model's license. The `onnx-community` export repositories declare no
license of their own on Hugging Face, only their `base_model`; the license above
is the base model's. The Qdrant e5 export is tagged MIT itself.

## Attribution

- **multilingual-e5-large**: Liang Wang, Nan Yang, Xiaolong Huang, Linjun Yang,
  Rangan Majumder, Furu Wei. *Multilingual E5 Text Embeddings: A Technical
  Report*, arXiv:2402.05672 (2024). MIT License, Copyright (c) Microsoft
  Corporation; the full text is in
  `services/embeddings/licenses/multilingual-e5-large-MIT.txt` and ships in the
  `-local` image under `/app/licenses/`.
- **gte-multilingual-reranker-base**: Alibaba-NLP, Apache-2.0.
- **bge-reranker-v2-m3**: BAAI (Beijing Academy of Artificial Intelligence),
  Apache-2.0.
- **BM25**: Qdrant, Apache-2.0.

## Choosing the reranker

The default reranker was picked with `services/embeddings/scripts/bench_rerank.py`
on a synthetic TR+EN set (`services/embeddings/bench/`):

| Model | nDCG@10 | Peak RSS (batch 8) |
|---|---|---|
| jina-reranker-v2 (previous default, non-commercial) | 0.980 | 0.79 GB |
| **gte-multilingual-reranker-base** (default) | 0.978 | 1.02 GB |
| bge-reranker-v2-m3 | 1.000 | 1.39 GB |

The latency numbers from that run came from an overloaded machine, so they are
left out here. Dated, reproducible latency results will be published in
`docs/benchmarks/`.

Switching the reranker does not change stored vectors, so it needs no
re-embedding. Switching the **dense** model does: see `docs/embeddings.md`.
