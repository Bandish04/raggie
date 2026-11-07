# SPDX-License-Identifier: Apache-2.0
"""Tests for check_web_env.py:  uv run --with pytest --with pyyaml pytest -q scripts/ci"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from check_web_env import compose_problems, is_secret_name, k8s_problems, main


@pytest.mark.parametrize(
    "name",
    [
        "JWT_SECRET",
        "POSTGRES_PASSWORD",
        "LLMAAS_API_KEY",
        "SETUP_TOKEN",
        "DATABASE_URL",
        "MINIO_ROOT_USER",
        "REDIS_PASS",
        "OIDC_CLIENT_SECRET",
        "SCIM_BEARER_TOKEN",
    ],
)
def test_secret_names(name: str) -> None:
    assert is_secret_name(name)


@pytest.mark.parametrize(
    "name",
    [
        "CONTROL_PLANE_URL",
        "SESSION_TTL_SECONDS",
        "MAX_TOKENS",
        "RETRIEVE_CONTEXT_K",
        "MONKEY_MODE",
        "NEXT_PUBLIC_DEFAULT_LOCALE",
        "ENABLE_HSTS",
    ],
)
def test_non_secret_names(name: str) -> None:
    assert not is_secret_name(name)


def _compose(web_env: dict) -> dict:
    return {
        "services": {"web": {"environment": web_env}, "edge": {"environment": {"JWT_SECRET": "x"}}}
    }


def test_compose_clean_web_passes_and_other_services_are_ignored() -> None:
    assert (
        compose_problems(_compose({"EDGE_URL": "http://edge:8080", "NODE_ENV": "production"})) == []
    )


def test_compose_flags_secret_keys_and_credentialed_urls() -> None:
    problems = compose_problems(
        _compose({"JWT_SECRET": "s", "REDIS_URL": "redis://:hunter2@redis:6379/0", "OK": "1"})
    )
    assert len(problems) == 2
    assert any("JWT_SECRET" in p for p in problems)
    assert any("REDIS_URL" in p and "hunter2" not in p for p in problems)


def test_compose_allowlist(tmp_path: Path) -> None:
    assert compose_problems(_compose({"PUBLIC_KEY_URL": "x"}), allow={"PUBLIC_KEY_URL"}) == []


def test_compose_without_web_service_fails() -> None:
    assert compose_problems({"services": {"edge": {}}})


def _k8s(web_container: dict, configmap_data: dict | None = None, name: str = "web") -> str:
    docs = [
        {
            "kind": "ConfigMap",
            "metadata": {"name": "raggie-config"},
            "data": configmap_data or {"EDGE_URL": "http://edge:8080"},
        },
        {
            "kind": "Deployment",
            "metadata": {"name": name},
            "spec": {"template": {"spec": {"containers": [web_container]}}},
        },
        {
            "kind": "Deployment",
            "metadata": {"name": "edge"},
            "spec": {
                "template": {
                    "spec": {
                        "containers": [
                            {"name": "edge", "envFrom": [{"secretRef": {"name": "raggie-secrets"}}]}
                        ]
                    }
                }
            },
        },
    ]
    return yaml.safe_dump_all(docs)


def test_k8s_clean_web_passes() -> None:
    web = {
        "name": "web",
        "envFrom": [{"configMapRef": {"name": "raggie-config"}}],
        "env": [{"name": "PORT", "value": "3000"}],
    }
    assert k8s_problems(_k8s(web)) == []


def test_k8s_flags_secret_ref_secret_key_ref_and_configmap_secrets() -> None:
    web = {
        "name": "web",
        "envFrom": [
            {"configMapRef": {"name": "raggie-config"}},
            {"secretRef": {"name": "raggie-secrets"}},
        ],
        "env": [{"name": "X", "valueFrom": {"secretKeyRef": {"name": "s", "key": "k"}}}],
    }
    problems = k8s_problems(_k8s(web, {"JWT_SECRET": "x", "EDGE_URL": "y"}))
    assert any("secretRef" in p for p in problems)
    assert any("secretKeyRef" in p for p in problems)
    assert any("JWT_SECRET" in p for p in problems)


def test_k8s_finds_the_helm_named_web_deployment() -> None:
    web = {"name": "web", "env": [{"name": "INTERNAL_API_SECRET", "value": "x"}]}
    assert k8s_problems(_k8s(web, name="raggie-web"))


def test_k8s_without_web_deployment_fails() -> None:
    assert k8s_problems(yaml.safe_dump_all([{"kind": "ConfigMap", "metadata": {"name": "c"}}]))


def test_main_exit_codes(tmp_path: Path) -> None:
    good = tmp_path / "compose.json"
    good.write_text(json.dumps(_compose({"EDGE_URL": "x"})))
    bad = tmp_path / "k8s.yaml"
    bad.write_text(_k8s({"name": "web", "envFrom": [{"secretRef": {"name": "s"}}]}))
    assert main(["--compose", str(good)]) == 0
    assert main(["--compose", str(good), "--k8s", str(bad)]) == 1
