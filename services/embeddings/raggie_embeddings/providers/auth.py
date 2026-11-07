# SPDX-License-Identifier: Apache-2.0

"""Internal bearer auth for the gateway's /v1/* routes.

Callers (edge, workers, control-plane) send ``Authorization: Bearer
$INTERNAL_API_SECRET``. On by default in cloud mode and with a remote reranker —
an upstream API key sits behind this service and must not be reachable by
anything on the network — and whenever INTERNAL_API_SECRET is set; off by
default only for a fully local install without a secret.
"""

from __future__ import annotations

import hmac
from collections.abc import Awaitable, Callable

from fastapi import Header, HTTPException, status

from raggie_embeddings.config import Settings


def internal_auth(cfg: Settings) -> Callable[..., Awaitable[None]]:
    expected = f"Bearer {cfg.internal_api_secret}".encode()

    async def dependency(authorization: str | None = Header(default=None)) -> None:
        if not cfg.require_auth:
            return
        if authorization is None or not hmac.compare_digest(authorization.encode(), expected):
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                "missing or invalid internal bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )

    return dependency
