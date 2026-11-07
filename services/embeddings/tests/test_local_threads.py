# SPDX-License-Identifier: Apache-2.0

from conftest import make_settings

import raggie_embeddings.providers.local as local_module


def _capture(monkeypatch):
    seen = {}

    class _Fake:
        def __init__(self, **kwargs):
            seen.update(kwargs)

    monkeypatch.setattr(local_module, "ensure_model", lambda name, cache: "/pinned/path")
    return seen, _Fake


def test_onnx_threads_reach_dense_and_reranker(monkeypatch) -> None:
    import fastembed
    import fastembed.rerank.cross_encoder as ce

    seen, fake = _capture(monkeypatch)
    monkeypatch.setattr(fastembed, "TextEmbedding", fake)
    cfg = make_settings(embeddings_onnx_threads=4)
    local_module.LocalDense.load(cfg)
    assert seen["threads"] == 4
    assert seen["specific_model_path"] == "/pinned/path"

    seen.clear()
    monkeypatch.setattr(ce, "TextCrossEncoder", fake)
    monkeypatch.setattr(local_module, "register_custom_rerankers", lambda: None)
    local_module.LocalReranker.load_model(cfg)
    assert seen["threads"] == 4


def test_onnx_threads_default_leaves_onnxruntime_default(monkeypatch) -> None:
    import fastembed

    seen, fake = _capture(monkeypatch)
    monkeypatch.setattr(fastembed, "TextEmbedding", fake)
    local_module.LocalDense.load(make_settings())
    assert "threads" not in seen


def test_onnx_threads_env(monkeypatch) -> None:
    monkeypatch.setenv("EMBEDDINGS_ONNX_THREADS", "2")
    assert make_settings().embeddings_onnx_threads == 2
