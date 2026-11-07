# SPDX-License-Identifier: Apache-2.0

from embeddings_stub import known_profile

from raggie_control_plane.main import app


def test_healthz(client) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"


def test_readyz(client, monkeypatch) -> None:
    # The shared test database may hold other suites' documents, which would make
    # the boot-time reconciliation report a mismatch; pin an accepted profile.
    monkeypatch.setattr(app.state, "embeddings_profile", known_profile())
    r = client.get("/readyz")
    assert r.status_code == 200
    assert r.json()["status"] == "ready"


def test_metrics(client) -> None:
    r = client.get("/metrics")
    assert r.status_code == 200
