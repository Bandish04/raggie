# SPDX-License-Identifier: Apache-2.0

"""Read-only root filesystem: at runtime the gateway reads baked models in place
and writes only under /tmp (no Hugging Face downloads, telemetry or caches)."""

import os
import re
import stat
from pathlib import Path

import pytest
from conftest import make_settings

import raggie_embeddings.providers.local as local_module
import raggie_embeddings.providers.models as models_module
from raggie_embeddings.providers.models import ModelNotAvailable, ensure_model, pinned_dir

DOCKERFILE = Path(__file__).resolve().parents[1] / "Dockerfile"


def _runtime_stage_env() -> dict[str, str]:
    text = DOCKERFILE.read_text(encoding="utf-8")
    runtime = text.rsplit("\nFROM ", 1)[1]  # last stage = runtime image
    env: dict[str, str] = {}
    for block in re.findall(r"^ENV (.+?)(?<!\\)$", runtime, flags=re.M | re.S):
        for key, value in re.findall(r'([A-Z_]+)=("[^"]*"|\S+)', block):
            env[key] = value.strip('"')
    return env


def test_runtime_image_is_offline_and_writes_only_under_tmp() -> None:
    env = _runtime_stage_env()
    assert env["HF_HUB_OFFLINE"] == "1"
    assert env["HF_HUB_DISABLE_TELEMETRY"] == "1"
    for key in ("HF_HOME", "XDG_CACHE_HOME", "TMPDIR"):
        assert env[key].startswith("/tmp"), key
    # The baked models stay visible (and are only read).
    assert env["FASTEMBED_CACHE_PATH"] == "/home/raggie/.cache/fastembed"


def test_bake_stage_is_not_offline() -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")
    models_stage = text.split("AS models", 1)[1].split("\nFROM ", 1)[0]
    assert "HF_HUB_OFFLINE=" not in models_stage  # it must download the snapshots


def test_baked_snapshot_is_read_without_writing(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    target = pinned_dir("Qdrant/bm25", str(tmp_path))
    target.mkdir(parents=True)
    (target / ".raggie-complete").touch()
    # Read-only like the image's model cache under readOnlyRootFilesystem.
    for path in (target, target.parent, tmp_path):
        path.chmod(stat.S_IRUSR | stat.S_IXUSR)

    def no_download(**_kw):
        raise AssertionError("must not download")

    monkeypatch.setattr(models_module, "_snapshot_download", no_download)
    try:
        assert ensure_model("Qdrant/bm25", str(tmp_path)) == str(target)
    finally:
        for path in (tmp_path, target.parent, target):
            path.chmod(stat.S_IRWXU)


def test_offline_missing_snapshot_fails_clearly_instead_of_downloading(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setattr(
        models_module, "_snapshot_download", lambda **_kw: pytest.fail("must not download")
    )
    with pytest.raises(ModelNotAvailable, match="EMBEDDINGS_BAKE") as excinfo:
        ensure_model("BAAI/bge-reranker-v2-m3", str(tmp_path))
    assert "HF_HUB_OFFLINE" in str(excinfo.value)


def test_online_missing_snapshot_downloads(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    calls = []

    def fake_download(**kwargs):
        calls.append(kwargs)
        Path(kwargs["local_dir"]).mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(models_module, "_snapshot_download", fake_download)
    path = ensure_model("Qdrant/bm25", str(tmp_path))
    assert calls and calls[0]["revision"] == models_module.PINNED["Qdrant/bm25"].revision
    assert (Path(path) / ".raggie-complete").exists()


def test_unpinned_model_in_offline_mode_loads_local_files_only(monkeypatch) -> None:
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    kwargs = local_module._model_kwargs("some/unpinned-model", make_settings())
    assert kwargs.get("local_files_only") is True
    assert "specific_model_path" not in kwargs


def test_offline_flag_parsing(monkeypatch) -> None:
    for value, expected in (("1", True), ("true", True), ("ON", True), ("0", False), ("", False)):
        monkeypatch.setenv("HF_HUB_OFFLINE", value)
        assert models_module.hf_offline() is expected
    monkeypatch.delenv("HF_HUB_OFFLINE")
    assert models_module.hf_offline() is False


def test_dockerignore_keeps_licenses() -> None:
    ignored = (DOCKERFILE.parent / ".dockerignore").read_text().split()
    assert not any(p.startswith("licenses") for p in ignored)
    assert os.path.isdir(DOCKERFILE.parent / "licenses")
