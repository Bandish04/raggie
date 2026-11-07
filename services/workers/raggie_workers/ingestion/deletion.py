# SPDX-License-Identifier: Apache-2.0

"""Deletion cascade consumer: document.deleted -> drop Qdrant chunks (+ object).

The control-plane soft-deletes/archives the document row and publishes
``raggie.document.deleted`` with::

    {"document_id", "workspace_id", "object_key", "collection", "purge_object": bool}

This consumer performs the heavy cascade out-of-band:
  - ARCHIVE (purge_object=false): remove the document's chunks from Qdrant so an
    archived doc stops surfacing in retrieval, but keep the raw object so the
    archive is reversible.
  - DELETE  (purge_object=true):  remove the Qdrant chunks AND hard-delete the
    MinIO object.

Both legs are idempotent: deleting already-absent points/objects is a no-op, and
a missing collection is treated as "nothing to delete". A handler error leaves
the event pending so another worker can reclaim and retry the cleanup.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from raggie_workers.bus import RedisStreamsBus
from raggie_workers.ingestion.collection import collection_name
from raggie_workers.ingestion.objectstore import ObjectStore
from raggie_workers.ingestion.vectorstore import QdrantVectorStore
from raggie_workers.topics import DOCUMENT_DELETED, INGESTION_GROUP

log = logging.getLogger("ingestion.deletion")


@dataclass
class DeletionConsumer:
    bus: RedisStreamsBus
    object_store: ObjectStore
    vector_store: QdrantVectorStore

    async def handle(self, payload: dict) -> None:
        document_id = payload["document_id"]
        # The publisher pins the collection; fall back to deriving it from the
        # embedding_dim if an older/partial payload omits it.
        collection = payload.get("collection")
        if not collection:
            dim = payload.get("embedding_dim")
            collection = collection_name(int(dim)) if dim else None
        purge_object = bool(payload.get("purge_object", False))
        workspace_id = payload.get("workspace_id")

        if workspace_id:
            # Every collection, not just the pinned one: a re-embed under a new
            # embedding profile leaves the document in the old collection too.
            purged = await self.vector_store.purge_document(document_id, workspace_id)
            log.info("deleted Qdrant chunks for document %s in %s", document_id, purged)
        elif collection:
            # Legacy event without workspace_id: a cross-collection purge could not
            # be tenant-scoped, so only the named collection is purged.
            await self.vector_store.delete_by_document(collection, document_id)
            log.warning(
                "document.deleted for %s has no workspace_id; purged only %s",
                document_id,
                collection,
            )
        else:
            log.warning(
                "document.deleted for %s has no collection — skipping Qdrant purge",
                document_id,
            )

        if purge_object:
            object_key = payload.get("object_key")
            if object_key:
                await self.object_store.remove(object_key)
                log.info("removed MinIO object %s for document %s", object_key, document_id)
            else:
                log.warning("purge_object set for %s but no object_key in payload", document_id)

    async def run_once(self, consumer_name: str = "deletion-1") -> int:
        await self.bus.ensure_group(DOCUMENT_DELETED, INGESTION_GROUP)
        msgs = await self.bus.consume(DOCUMENT_DELETED, INGESTION_GROUP, consumer_name)
        for msg_id, payload in msgs:
            try:
                await self.handle(payload)
            except Exception:  # noqa: BLE001 — cleanup is best-effort; never wedge the lane
                log.exception("deletion handler failed for payload %s", payload)
                # Keep the event pending. RedisStreamsBus will reclaim it after
                # the idle timeout, so transient cleanup failures are retried.
                continue
            await self.bus.ack(DOCUMENT_DELETED, INGESTION_GROUP, msg_id)
        return len(msgs)
