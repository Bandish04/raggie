# SPDX-License-Identifier: Apache-2.0

"""Spec preparation for the authenticated ZAP API scans (bootstrap.py)."""

from __future__ import annotations

import json
from pathlib import Path

from bootstrap import EDGE_SPEC, SESSION_KILLERS, prepare_cp_spec, render_edge_spec


def _spec() -> dict:
    return {
        "openapi": "3.1.0",
        "servers": [{"url": "http://control-plane:8000"}],
        "paths": {
            "/api/v1/auth/login": {"post": {}},
            "/api/v1/auth/logout": {"post": {}},
            "/api/v1/auth/change-password": {"post": {}},
            "/api/v1/auth/me": {"get": {}},
            "/api/v1/admin/workspaces/{workspace_id}/widget": {"get": {}, "put": {}},
        },
    }


def test_cp_spec_targets_the_stack_and_drops_session_killers() -> None:
    out = prepare_cp_spec(_spec(), "http://127.0.0.1:58000")

    assert out["servers"] == [{"url": "http://127.0.0.1:58000"}]
    assert not SESSION_KILLERS & out["paths"].keys()
    assert {"/api/v1/auth/login", "/api/v1/auth/me"} <= out["paths"].keys()
    assert out["paths"]["/api/v1/admin/workspaces/{workspace_id}/widget"] == {"get": {}, "put": {}}


def test_cp_spec_does_not_mutate_its_input() -> None:
    spec = _spec()
    prepare_cp_spec(spec, "http://127.0.0.1:58000")
    assert "/api/v1/auth/logout" in spec["paths"]


def test_edge_spec_covers_exactly_the_public_widget_surface() -> None:
    template = json.loads(Path(EDGE_SPEC).read_text())
    assert set(template["paths"]) == {
        "/api/v1/widget/token",
        "/api/v1/chat/stream",
        "/widgets/embed.js",
    }
    assert not any("/internal/" in p or "/admin/" in p for p in template["paths"])


def test_edge_spec_renders_server_and_workspace_examples() -> None:
    template = json.loads(Path(EDGE_SPEC).read_text())
    out = render_edge_spec(template, "http://localhost:8380", "ws-123")

    assert out["servers"] == [{"url": "http://localhost:8380"}]
    for path in ("/api/v1/widget/token", "/api/v1/chat/stream"):
        schema = out["paths"][path]["post"]["requestBody"]["content"]["application/json"]["schema"]
        assert schema["properties"]["workspace_id"]["example"] == "ws-123"
    assert "ws-123" not in json.dumps(template)  # template untouched
