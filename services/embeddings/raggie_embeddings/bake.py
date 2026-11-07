# SPDX-License-Identifier: Apache-2.0

"""Download (bake) the pinned local models into the image at build time.

    python -m raggie_embeddings.bake dense,sparse,rerank   # -local image
    python -m raggie_embeddings.bake sparse                # -slim (cloud) image

Each model is loaded once after download so a broken snapshot fails the build
instead of the first request. Only the pinned default models (the ones MODELS.md
marks as baked) are ever baked: EMBEDDINGS_MODEL / SPARSE_MODEL / RERANKER_MODEL
in the build environment are ignored, so a release image can never ship an
opt-in model (e.g. a non-commercial reranker). Operators who want another model
point the running service at it instead.
"""

from __future__ import annotations

import sys

from raggie_embeddings.config import Settings
from raggie_embeddings.providers.local import LocalDense, LocalReranker, LocalSparse

_COMPONENTS = ("dense", "sparse", "rerank")
# Component -> Settings field naming the model it bakes.
_MODEL_FIELDS = {"dense": "embeddings_model", "sparse": "sparse_model", "rerank": "reranker_model"}


def _default_model(component: str) -> str:
    return Settings.model_fields[_MODEL_FIELDS[component]].default


def pinned_settings() -> Settings:
    """Settings whose model ids are the code defaults, whatever the env says."""
    return Settings(_env_file=None, **{f: _default_model(c) for c, f in _MODEL_FIELDS.items()})


def bake(components: list[str], cfg: Settings) -> None:
    unknown = sorted(set(components) - set(_COMPONENTS))
    if unknown:
        raise SystemExit(
            f"unknown bake component(s): {', '.join(unknown)}; choose from {', '.join(_COMPONENTS)}"
        )
    for component in components:
        model = getattr(cfg, _MODEL_FIELDS[component])
        if model != _default_model(component):
            raise SystemExit(
                f"refusing to bake non-default {component} model {model!r}; "
                f"only {_default_model(component)!r} ships in images"
            )
    if "dense" in components:
        print(f"baking dense: {cfg.embeddings_model}", flush=True)
        LocalDense.load(cfg)
    if "sparse" in components:
        print(f"baking sparse: {cfg.sparse_model}", flush=True)
        if not LocalSparse.load(cfg).available:
            raise SystemExit(f"sparse model {cfg.sparse_model} failed to load")
    if "rerank" in components:
        print(f"baking rerank: {cfg.reranker_model}", flush=True)
        LocalReranker.load_model(cfg)


def main(argv: list[str]) -> None:
    raw = argv[1] if len(argv) > 1 else ",".join(_COMPONENTS)
    components = [c.strip() for c in raw.split(",") if c.strip()]
    bake(components, pinned_settings())


if __name__ == "__main__":
    main(sys.argv)
