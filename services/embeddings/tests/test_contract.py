# SPDX-License-Identifier: Apache-2.0

"""Contract: local-stub and cloud-mock gateways return the same shapes, and both
validate against contracts/embeddings_gateway.schema.json (shared with the Go
edge and the Python callers)."""

import json
from pathlib import Path

import httpx
import jsonschema
import pytest
import respx
from fakes import cloud_mock_app, local_stub_app, openai_upstream, wait_ready
from fastapi.testclient import TestClient

from raggie_embeddings import schemas

SCHEMA_PATH = Path(__file__).resolve().parents[3] / "contracts" / "embeddings_gateway.schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
AUTH = {"Authorization": "Bearer " + "s" * 40}

CALLS = {
    "embeddings": (
        "post",
        "/v1/embeddings",
        {"input": ["birinci", "second"]},
        "EmbeddingsResponse",
    ),
    "embeddings_query": (
        "post",
        "/v1/embeddings",
        {"input": "q", "input_type": "query"},
        "EmbeddingsResponse",
    ),
    "query": ("post", "/v1/query", {"query": "izin politikası nedir?"}, "QueryResponse"),
    "sparse": ("post", "/v1/sparse", {"input": ["a b", "c"]}, "SparseResponse"),
    "rerank": (
        "post",
        "/v1/rerank",
        {"query": "q", "documents": ["a", "bbb", "cc"], "top_n": 2},
        "RerankResponse",
    ),
    "info": ("get", "/v1/info", None, "InfoResponse"),
    "readyz": ("get", "/readyz", None, "ReadyResponse"),
}


def _validator(definition: str) -> jsonschema.Draft202012Validator:
    return jsonschema.Draft202012Validator({"$ref": f"#/$defs/{definition}", **SCHEMA})


def _shape(value):
    """Structural fingerprint: keys and JSON types, not values or lengths."""
    if isinstance(value, dict):
        return {k: _shape(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return [_shape(value[0])] if value else []
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int | float):
        return "number"
    if value is None:
        return "null-or-string"
    if isinstance(value, str):
        return "null-or-string"
    return type(value).__name__


def _collect(client: TestClient, headers: dict) -> dict[str, dict]:
    out = {}
    for name, (method, path, body, _definition) in CALLS.items():
        if method == "post":
            response = client.post(path, json=body, headers=headers)
        else:
            response = client.get(path, headers=headers)
        assert response.status_code == 200, (name, response.text)
        out[name] = response.json()
    return out


@pytest.fixture
def responses(cloud_settings):
    cloud_cfg = cloud_settings.model_copy(
        update={
            "embedding_dim": 8,
            "embeddings_request_extra_json": "",
            "sparse_enabled": True,
            "reranker_provider": "cohere",
            "reranker_model": "rerank-v3.5",
            "reranker_upstream_url": "https://rerank.example/v2/rerank",
            "reranker_upstream_api_key": "rk",
        }
    )
    local_cfg = cloud_settings.model_copy(
        update={
            "embeddings_provider": "local",
            "embeddings_model": "intfloat/multilingual-e5-large",
            "embedding_dim": 8,
            "embeddings_request_extra_json": "",
            "sparse_enabled": True,
            "embeddings_require_auth": True,  # same auth posture for a fair comparison
        }
    )
    with respx.mock:
        respx.post("https://api.openai.example/v1/embeddings").mock(
            side_effect=lambda r: openai_upstream(r, dim=8)
        )
        respx.post("https://rerank.example/v2/rerank").mock(
            side_effect=lambda r: httpx.Response(
                200,
                json={
                    "results": [
                        {"index": i, "relevance_score": 1.0 / (i + 1)}
                        for i in range(len(json.loads(r.content)["documents"]))
                    ]
                },
            )
        )
        result = {}
        apps = (("local", local_stub_app(local_cfg)), ("cloud", cloud_mock_app(cloud_cfg)))
        for mode, app in apps:
            with TestClient(app) as client:
                assert wait_ready(client).status_code == 200
                result[mode] = _collect(client, AUTH)
    return result


@pytest.mark.parametrize("mode", ["local", "cloud"])
@pytest.mark.parametrize("call", list(CALLS))
def test_responses_validate_against_shared_schema(responses, mode: str, call: str) -> None:
    definition = CALLS[call][3]
    errors = sorted(_validator(definition).iter_errors(responses[mode][call]), key=str)
    assert not errors, [e.message for e in errors]


@pytest.mark.parametrize("call", list(CALLS))
def test_local_and_cloud_shapes_are_identical(responses, call: str) -> None:
    assert _shape(responses["local"][call]) == _shape(responses["cloud"][call])


def test_error_body_matches_schema() -> None:
    validator = _validator("ErrorResponse")
    validator.validate({"detail": "embedding upstream unavailable (429); retry later"})


@pytest.mark.parametrize(
    ("model", "definition"),
    [
        (schemas.EmbeddingsRequest, "EmbeddingsRequest"),
        (schemas.EmbeddingsResponse, "EmbeddingsResponse"),
        (schemas.SparseRequest, "SparseRequest"),
        (schemas.QueryRequest, "QueryRequest"),
        (schemas.QueryResponse, "QueryResponse"),
        (schemas.RerankRequest, "RerankRequest"),
        (schemas.RerankResponse, "RerankResponse"),
        (schemas.InfoResponse, "InfoResponse"),
        (schemas.ErrorResponse, "ErrorResponse"),
    ],
)
def test_pydantic_models_and_contract_do_not_drift(model, definition: str) -> None:
    contract = SCHEMA["$defs"][definition]
    assert set(model.model_fields) == set(contract["properties"]), definition
    # Everything the model requires, the contract requires too (and vice versa
    # for responses, whose fields are always serialized).
    model_required = {n for n, f in model.model_fields.items() if f.is_required()}
    assert model_required <= set(contract.get("required", [])), definition
    if definition.endswith("Response"):
        assert set(contract.get("required", [])) == set(model.model_fields), definition
