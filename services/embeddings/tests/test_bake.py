# SPDX-License-Identifier: Apache-2.0

import pytest
from conftest import make_settings

import raggie_embeddings.bake as bake_module
from raggie_embeddings.providers.models import PINNED, pinned_dir


def test_unknown_component_fails() -> None:
    with pytest.raises(SystemExit, match="unknown bake component"):
        bake_module.bake(["dense", "gpu"], make_settings())


def test_slim_bakes_only_sparse(monkeypatch) -> None:
    loaded: list[str] = []
    monkeypatch.setattr(bake_module.LocalDense, "load", lambda cfg: loaded.append("dense"))
    monkeypatch.setattr(
        bake_module.LocalReranker, "load_model", staticmethod(lambda cfg: loaded.append("rerank"))
    )

    class _Sparse:
        available = True

    monkeypatch.setattr(
        bake_module.LocalSparse, "load", lambda cfg: loaded.append("sparse") or _Sparse()
    )
    bake_module.bake(["sparse"], make_settings())
    assert loaded == ["sparse"]


def test_default_models_are_all_pinned_to_exact_revisions() -> None:
    cfg = make_settings()
    for name in (
        cfg.embeddings_model,
        cfg.sparse_model,
        cfg.reranker_model,
        "BAAI/bge-reranker-v2-m3",
    ):
        pin = PINNED[name]
        assert len(pin.revision) == 40 and all(c in "0123456789abcdef" for c in pin.revision)
        assert pin.revision in str(pinned_dir(name, "/cache"))


def test_default_reranker_is_not_non_commercial() -> None:
    assert PINNED[make_settings().reranker_model].license == "apache-2.0"


def _record_loads(monkeypatch) -> dict[str, str]:
    baked: dict[str, str] = {}
    monkeypatch.setattr(
        bake_module.LocalDense, "load", lambda cfg: baked.__setitem__("dense", cfg.embeddings_model)
    )
    monkeypatch.setattr(
        bake_module.LocalReranker,
        "load_model",
        staticmethod(lambda cfg: baked.__setitem__("rerank", cfg.reranker_model)),
    )

    class _Sparse:
        available = True

    monkeypatch.setattr(
        bake_module.LocalSparse,
        "load",
        lambda cfg: baked.__setitem__("sparse", cfg.sparse_model) or _Sparse(),
    )
    return baked


def test_release_bake_ignores_model_env_overrides(monkeypatch) -> None:
    # A build-time env (e.g. an added ARG) must never swap a non-default model,
    # such as the CC-BY-NC jina reranker, into a release image.
    monkeypatch.setenv("RERANKER_MODEL", "jinaai/jina-reranker-v2-base-multilingual")
    monkeypatch.setenv("EMBEDDINGS_MODEL", "BAAI/bge-m3")
    monkeypatch.setenv("SPARSE_MODEL", "prithivida/Splade_PP_en_v1")
    baked = _record_loads(monkeypatch)

    bake_module.main(["bake", "dense,sparse,rerank"])

    # The code defaults (make_settings() would read the same overridden env).
    fields = bake_module.Settings.model_fields
    assert baked == {
        "dense": fields["embeddings_model"].default,
        "sparse": fields["sparse_model"].default,
        "rerank": fields["reranker_model"].default,
    }


def test_bake_refuses_a_non_default_model(monkeypatch) -> None:
    _record_loads(monkeypatch)
    cfg = make_settings(reranker_model="jinaai/jina-reranker-v2-base-multilingual")
    with pytest.raises(SystemExit, match="non-default"):
        bake_module.bake(["rerank"], cfg)
