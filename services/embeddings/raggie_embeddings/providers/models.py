# SPDX-License-Identifier: Apache-2.0

"""Pinned ONNX model snapshots for the local providers.

Every model the gateway ships with is fetched at an exact Hugging Face commit
(never "latest") into ``{cache_dir}/pinned/<repo>@<revision>`` as plain files,
then handed to fastembed via ``specific_model_path``. The ``-local`` image bakes
these directories at build time (``python -m raggie_embeddings.bake``), so a
running container needs no network. Model ids that are not pinned here fall
back to fastembed's own (unpinned) download, with a warning.

Read-only root filesystem: a baked snapshot is only read (the completion
marker is checked, nothing is written). With HF_HUB_OFFLINE=1 (set in the
runtime image) a missing snapshot is a clear error instead of an attempted
download into the read-only cache.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("raggie.embeddings.models")

_COMPLETE_MARKER = ".raggie-complete"
_TOKENIZER_FILES = (
    "config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
)


class ModelNotAvailable(RuntimeError):
    """A model is not baked into this image and downloads are disabled."""


def hf_offline() -> bool:
    return os.environ.get("HF_HUB_OFFLINE", "").strip().lower() in {"1", "true", "yes", "on"}


def _snapshot_download(*, repo_id: str, revision: str, **kwargs) -> str:
    # revision is required: every download is pinned to an exact commit.
    from huggingface_hub import snapshot_download

    return snapshot_download(repo_id=repo_id, revision=revision, **kwargs)


@dataclass(frozen=True)
class PinnedModel:
    repo: str
    revision: str
    files: tuple[str, ...]
    # fastembed model_file for models registered via add_custom_model.
    model_file: str | None = None
    license: str = ""
    size_in_gb: float = 0.0


PINNED: dict[str, PinnedModel] = {
    # Dense (fastembed's own ONNX export of intfloat/multilingual-e5-large).
    "intfloat/multilingual-e5-large": PinnedModel(
        repo="qdrant/multilingual-e5-large-onnx",
        revision="ac6781cd1cf88b8306a536d7c9d18a5bd57cc14b",
        files=("model.onnx", "model.onnx_data", "sentencepiece.bpe.model", *_TOKENIZER_FILES),
        license="mit",
    ),
    # Sparse BM25 (stopword lists + config only; no weights).
    "Qdrant/bm25": PinnedModel(
        repo="Qdrant/bm25",
        revision="22b8d2af71a76161e18dd432d2cee0eefa66e412",
        files=("*.txt", "*.json"),
        license="apache-2.0",
    ),
    # Default reranker: Apache-2.0, int8 ONNX export.
    "Alibaba-NLP/gte-multilingual-reranker-base": PinnedModel(
        repo="onnx-community/gte-multilingual-reranker-base",
        revision="ee64367e35a2db0da46bb6497e13a18f8bd585cb",
        files=("onnx/model_int8.onnx", *_TOKENIZER_FILES),
        model_file="onnx/model_int8.onnx",
        license="apache-2.0",
        size_in_gb=0.34,
    ),
    # Fallback reranker: Apache-2.0, higher quality, ~2x slower on CPU.
    "BAAI/bge-reranker-v2-m3": PinnedModel(
        repo="onnx-community/bge-reranker-v2-m3-ONNX",
        revision="6f5ff65298512715a1e669753bc754d2bc8f367b",
        files=("onnx/model_int8.onnx", *_TOKENIZER_FILES),
        model_file="onnx/model_int8.onnx",
        license="apache-2.0",
        size_in_gb=0.57,
    ),
    # Previous default. CC-BY-NC-4.0 (non-commercial): opt-in only, kept so
    # existing deployments can pin it explicitly and for the benchmark baseline.
    "jinaai/jina-reranker-v2-base-multilingual": PinnedModel(
        repo="jinaai/jina-reranker-v2-base-multilingual",
        revision="9cfeff2df7d40d1b78e75e5e9cebec92a99813c9",
        files=("onnx/model.onnx", *_TOKENIZER_FILES),
        license="cc-by-nc-4.0",
    ),
}


def pinned_dir(model_name: str, cache_dir: str) -> Path | None:
    pin = PINNED.get(model_name)
    if pin is None:
        return None
    return Path(cache_dir) / "pinned" / f"{pin.repo.replace('/', '--')}@{pin.revision}"


def ensure_model(model_name: str, cache_dir: str) -> str | None:
    """Local path of the pinned snapshot (downloading it once), or None when the
    model is not pinned and fastembed should resolve it itself."""
    target = pinned_dir(model_name, cache_dir)
    if target is None:
        logger.warning(
            "model %s is not pinned; fastembed downloads its latest revision", model_name
        )
        return None
    if (target / _COMPLETE_MARKER).exists():
        return str(target)
    if hf_offline():
        raise ModelNotAvailable(
            f"model {model_name} is not baked into this image and HF_HUB_OFFLINE=1; "
            "rebuild with EMBEDDINGS_BAKE including it, or set HF_HUB_OFFLINE=0 with a "
            "writable FASTEMBED_CACHE_PATH volume"
        )
    pin = PINNED[model_name]
    logger.info("downloading %s@%s", pin.repo, pin.revision[:12])
    _snapshot_download(
        repo_id=pin.repo,
        revision=pin.revision,
        allow_patterns=list(pin.files),
        local_dir=str(target),
    )
    (target / _COMPLETE_MARKER).touch()
    return str(target)


_registered: set[str] = set()


def register_custom_rerankers() -> None:
    """Teach fastembed the pinned cross-encoders it does not ship with."""
    from fastembed.common.model_description import ModelSource
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    known = {m["model"] for m in TextCrossEncoder.list_supported_models()}
    for name, pin in PINNED.items():
        if pin.model_file is None or name in known or name in _registered:
            continue
        TextCrossEncoder.add_custom_model(
            model=name,
            sources=ModelSource(hf=pin.repo),
            model_file=pin.model_file,
            license=pin.license,
            size_in_gb=pin.size_in_gb,
        )
        _registered.add(name)
