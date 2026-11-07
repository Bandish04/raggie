# SPDX-License-Identifier: Apache-2.0

import json
from pathlib import Path

import pytest

from raggie_workers.ingestion.collection import collection_name

# contracts/ lives at the repo root: services/workers/tests -> up 3 -> repo root.
_CONTRACT = Path(__file__).resolve().parents[3] / "contracts" / "qdrant_collection.json"


def test_collection_name_matches_contract_vectors() -> None:
    contract = json.loads(_CONTRACT.read_text(encoding="utf-8"))
    for vector in contract["vectors"]:
        assert collection_name(vector["dim"]) == vector["name"]


def test_collection_name_rejects_nonpositive_dim() -> None:
    with pytest.raises(ValueError):
        collection_name(0)
