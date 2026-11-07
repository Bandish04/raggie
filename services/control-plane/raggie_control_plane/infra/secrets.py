# SPDX-License-Identifier: Apache-2.0

"""Secret manager seam.

Resolves a secret from, in order: a `<NAME>_FILE` env pointing at a mounted file
(the Docker/Kubernetes/Vault-agent convention), then the plain `<NAME>` env,
then the in-code default. This lets prod inject secrets as files (sealed-secrets
/ external-secrets / Vault) with zero code change and keeps plaintext out of the
environment and image."""

from __future__ import annotations

import os
from pathlib import Path


def resolve_secret(env_name: str, current: str) -> str:
    file_path = os.environ.get(f"{env_name}_FILE")
    if file_path:
        p = Path(file_path)
        if p.is_file():
            return p.read_text(encoding="utf-8").strip()
    return current
