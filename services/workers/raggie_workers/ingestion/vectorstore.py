# SPDX-License-Identifier: Apache-2.0

"""Qdrant vector store adapter (async).

Collections use NAMED vectors so dense + sparse can coexist for hybrid search:
  - "dense":  the embedding-model vector (cosine, HNSW-tuned).
  - "bm25":   a BM25 sparse vector with Qdrant's IDF modifier.
Sparse is optional per point — when absent, the point is dense-only and the
dense-named search still works (graceful degradation to dense-only retrieval).
"""

from __future__ import annotations

from dataclasses import dataclass

from qdrant_client import AsyncQdrantClient, models
from qdrant_client.http.exceptions import UnexpectedResponse

from raggie_workers.ingestion.collection import COLLECTION_PREFIX

# Named-vector keys — MUST match the edge's hybrid query ("using": "dense"/"bm25").
DENSE_VECTOR = "dense"
SPARSE_VECTOR = "bm25"


@dataclass
class ChunkPoint:
    id: str
    dense: list[float]
    payload: dict
    sparse_indices: list[int] | None = None
    sparse_values: list[float] | None = None


class QdrantVectorStore:
    def __init__(
        self,
        client: AsyncQdrantClient,
        *,
        replication_factor: int = 1,
        shard_number: int = 1,
        write_consistency_factor: int = 1,
    ) -> None:
        self.client = client
        # Applied only when this store CREATES a collection (HA clusters);
        # existing collections keep their topology.
        self.replication_factor = replication_factor
        self.shard_number = shard_number
        self.write_consistency_factor = write_consistency_factor

    async def ensure_collection(self, name: str, dim: int) -> None:
        if await self.client.collection_exists(name):
            return
        # IDEMPOTENT / race-safe: under concurrent ingestion many workers can pass
        # the exists check at once and all try to create — only one wins; the rest
        # get 409 "already exists". Swallow any create error AS LONG AS the
        # collection exists afterwards (a peer created it); only re-raise a genuine
        # failure where the collection still does not exist.
        try:
            await self.client.create_collection(
                collection_name=name,
                shard_number=self.shard_number,
                replication_factor=self.replication_factor,
                write_consistency_factor=self.write_consistency_factor,
                vectors_config={
                    DENSE_VECTOR: models.VectorParams(
                        size=dim,
                        distance=models.Distance.COSINE,
                        # Recall-first HNSW tuning (build-time). Higher m/ef_construct =
                        # better recall at a modest index-build cost.
                        hnsw_config=models.HnswConfigDiff(m=32, ef_construct=256),
                    ),
                },
                sparse_vectors_config={
                    # IDF modifier is REQUIRED for correct BM25 scoring: fastembed BM25
                    # documents carry term frequencies and Qdrant multiplies in IDF.
                    SPARSE_VECTOR: models.SparseVectorParams(modifier=models.Modifier.IDF),
                },
            )
            # Keyword payload indexes keep workspace-filtered search fast at scale
            # and make per-document filter/delete cheap.
            await self.client.create_payload_index(
                collection_name=name,
                field_name="workspace_id",
                field_schema=models.PayloadSchemaType.KEYWORD,
            )
            await self.client.create_payload_index(
                collection_name=name,
                field_name="document_id",
                field_schema=models.PayloadSchemaType.KEYWORD,
            )
        except Exception:
            if not await self.client.collection_exists(name):
                raise

    async def upsert(self, name: str, points: list[ChunkPoint]) -> None:
        if not points:
            return
        structs: list[models.PointStruct] = []
        for p in points:
            vector: dict = {DENSE_VECTOR: p.dense}
            if p.sparse_indices and p.sparse_values:
                vector[SPARSE_VECTOR] = models.SparseVector(
                    indices=p.sparse_indices, values=p.sparse_values
                )
            structs.append(models.PointStruct(id=p.id, vector=vector, payload=p.payload))
        await self.client.upsert(collection_name=name, points=structs)

    async def delete_by_document(self, name: str, document_id: str) -> None:
        """Delete every chunk of a document by a `document_id` payload filter.

        Idempotent + fail-soft: if the collection does not exist (e.g. it was
        never created because ingestion never ran, or a peer already dropped
        it), there is nothing to delete and we return quietly. Deleting points
        that match no filter is a Qdrant no-op.
        """
        if not await self.client.collection_exists(name):
            return
        await self.client.delete(
            collection_name=name,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="document_id",
                            match=models.MatchValue(value=document_id),
                        )
                    ]
                )
            ),
        )

    async def purge_document(self, document_id: str, workspace_id: str) -> list[str]:
        """Delete a document's chunks from EVERY Raggie collection (KVKK: after an
        embedding-profile change the old collection still holds them, payload text
        included). Scoped by document_id AND workspace_id, so a purge can never
        reach another tenant's points. Event collections always carry the prefix
        (contracts/qdrant_collection.json). Idempotent; returns the collections
        purged."""
        listed = (await self.client.get_collections()).collections
        names = sorted(c.name for c in listed if c.name.startswith(COLLECTION_PREFIX))
        selector = models.FilterSelector(
            filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="document_id", match=models.MatchValue(value=document_id)
                    ),
                    models.FieldCondition(
                        key="workspace_id", match=models.MatchValue(value=workspace_id)
                    ),
                ]
            )
        )
        for name in names:
            try:
                await self.client.delete(collection_name=name, points_selector=selector)
            except UnexpectedResponse as exc:
                if exc.status_code != 404:  # dropped since we listed it: nothing to purge
                    raise
        return names

    async def delete_stale_document_chunks(
        self, name: str, document_id: str, keep_count: int
    ) -> None:
        """Remove trailing points left by re-ingesting a shorter document."""
        if keep_count <= 0:
            await self.delete_by_document(name, document_id)
            return
        if not await self.client.collection_exists(name):
            return
        await self.client.delete(
            collection_name=name,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="document_id",
                            match=models.MatchValue(value=document_id),
                        ),
                        models.FieldCondition(
                            key="chunk_index",
                            range=models.Range(gte=keep_count),
                        ),
                    ]
                )
            ),
        )

    async def search(
        self, name: str, vector: list[float], workspace_id: str, k: int = 4
    ) -> list[dict]:
        # Dense-only search against the named "dense" vector (used by tests/tools;
        # the edge does the full hybrid query).
        resp = await self.client.query_points(
            collection_name=name,
            query=vector,
            using=DENSE_VECTOR,
            query_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="workspace_id",
                        match=models.MatchValue(value=workspace_id),
                    )
                ]
            ),
            limit=k,
            with_payload=True,
        )
        return [{"score": pt.score, **(pt.payload or {})} for pt in resp.points]
