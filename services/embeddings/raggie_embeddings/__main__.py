# SPDX-License-Identifier: Apache-2.0

"""``python -m raggie_embeddings``: serve the gateway on EMBEDDINGS_PORT."""

import uvicorn

from raggie_embeddings.config import Settings

uvicorn.run(
    "raggie_embeddings.main:app",
    host="0.0.0.0",  # container entrypoint: the orchestrator decides exposure
    port=Settings().embeddings_port,
)
