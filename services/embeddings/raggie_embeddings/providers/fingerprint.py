# SPDX-License-Identifier: Apache-2.0

"""Embedding-profile fingerprint and the Qdrant collection it maps to.

The fingerprint identifies everything that changes the vectors a document gets:
provider, model, dimension, instruction prefixes and provider-specific request
fields. Upstream URL and API key are deliberately excluded, so rotating a key
or moving behind a proxy never forces a re-embed.

Collections:
  - the legacy profile (local multilingual-e5-large, 1024-d, E5 prefixes, no
    extras) keeps ``raggie_chunks_d1024`` — zero migration for existing installs;
  - every other profile gets ``raggie_chunks_d{dim}_{fp}``, so two models never
    share a collection even at the same dimension.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from raggie_embeddings.config import (
    E5_PASSAGE_PREFIX,
    E5_QUERY_PREFIX,
    LEGACY_DENSE_MODEL,
    LEGACY_DIM,
    Settings,
)

FINGERPRINT_LENGTH = 8
LEGACY_COLLECTION = f"raggie_chunks_d{LEGACY_DIM}"


@dataclass(frozen=True)
class Profile:
    provider: str
    model: str
    dim: int
    query_prefix: str
    passage_prefix: str
    request_extra: dict[str, Any] = field(default_factory=dict)
    query_extra: dict[str, Any] = field(default_factory=dict)
    passage_extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_settings(cls, cfg: Settings) -> Profile:
        return cls(
            provider=cfg.embeddings_provider,
            model=cfg.embeddings_model,
            dim=cfg.embedding_dim,
            query_prefix=cfg.query_prefix,
            passage_prefix=cfg.passage_prefix,
            request_extra=cfg.request_extra,
            query_extra=cfg.query_extra,
            passage_extra=cfg.passage_extra,
        )

    @property
    def is_legacy(self) -> bool:
        return (
            self.provider == "local"
            and self.model == LEGACY_DENSE_MODEL
            and self.dim == LEGACY_DIM
            and self.query_prefix == E5_QUERY_PREFIX
            and self.passage_prefix == E5_PASSAGE_PREFIX
            and not (self.request_extra or self.query_extra or self.passage_extra)
        )


def canonical_json(profile: Profile) -> str:
    return json.dumps(asdict(profile), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def fingerprint(profile: Profile) -> str:
    digest = hashlib.sha256(canonical_json(profile).encode("utf-8")).hexdigest()
    return digest[:FINGERPRINT_LENGTH]


def collection_name(profile: Profile) -> str:
    if profile.is_legacy:
        return LEGACY_COLLECTION
    return f"raggie_chunks_d{profile.dim}_{fingerprint(profile)}"
