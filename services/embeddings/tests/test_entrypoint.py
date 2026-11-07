# SPDX-License-Identifier: Apache-2.0

import runpy

import uvicorn


def test_module_entrypoint_listens_on_embeddings_port(monkeypatch) -> None:
    seen = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: seen.update(app=app, **kw))
    monkeypatch.setenv("EMBEDDINGS_PORT", "9123")
    runpy.run_module("raggie_embeddings", run_name="__main__")
    assert seen["app"] == "raggie_embeddings.main:app"
    assert (seen["host"], seen["port"]) == ("0.0.0.0", 9123)


def test_image_uses_the_entrypoint_and_probes_the_configured_port() -> None:
    from pathlib import Path

    dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text()
    assert 'CMD ["python", "-m", "raggie_embeddings"]' in dockerfile
    assert "EMBEDDINGS_PORT" in dockerfile.split("HEALTHCHECK", 1)[1]
