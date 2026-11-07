# SPDX-License-Identifier: Apache-2.0

"""``python -m raggie_embeddings``: serve the gateway on EMBEDDINGS_PORT."""

import uvicorn

from raggie_embeddings.config import Settings

uvicorn.run(
    "raggie_embeddings.main:app",
    # Container entrypoint: the orchestrator decides exposure.
    host="0.0.0.0",  # nosec B104
    port=Settings().embeddings_port,
)
