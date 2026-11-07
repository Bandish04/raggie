# Event contract (single source of truth)

Wire envelope (Redis-protocol Streams, served by Valkey; a Redpanda adapter is planned): each message has a
single field **`data`** holding a JSON object — the payload below. The
control-plane produces; the workers consume (consumer groups + ack).

## `raggie.document.uploaded`
Emitted after a file is stored and its `documents` row is (re-)armed `PENDING`.
Consumed by ingestion workers. Producers:

- control-plane — upload (direct and multipart), workspace re-index,
  `reindex-all`, manual `retry-failed`, and the embedding re-embed
  (`POST /api/v1/admin/embeddings/reembed`, or boot with
  `EMBEDDINGS_FINGERPRINT_POLICY=auto_reindex`). Each targets the embeddings
  gateway's CURRENT profile (`GET /v1/info`) and writes the same `collection` /
  `embedding_fingerprint` onto the documents row.
- scheduler worker — the failed-ingestion retry sweep, which replays the
  document's stored `qdrant_collection_name` / `embedding_fingerprint`.

```json
{
  "document_id": "uuid",
  "workspace_id": "uuid",
  "filename": "string",
  "object_key": "string (object-store key of the raw upload)",
  "embedding_dim": 1024,
  "collection": "raggie_chunks_d1024 | raggie_chunks_d{dim}_{fingerprint}",
  "embedding_fingerprint": "2872ae6a"
}
```

`collection` and `embedding_fingerprint` are additive (absent from producers
that predate the embeddings gateway). When present, `collection` is
authoritative: consumers write there instead of deriving a name from
`embedding_dim`, and an `embedding_fingerprint` different from the gateway's
active one is a terminal failure (the document must be re-embedded, never
mixed into another vector space). `embedding_dim` stays for older consumers.
See contracts/embeddings_gateway.schema.json for both formats.

## `raggie.document.processed`
Emitted by an ingestion worker on success.

```json
{ "document_id": "uuid", "chunks": 123, "collection": "raggie_chunks_d1024" }
```

## `raggie.document.failed`
Emitted by an ingestion worker on failure (document marked `FAILED`).

```json
{ "document_id": "uuid", "error": "string" }
```

## `raggie.document.deleted`
Emitted by the control-plane when a document is archived or (soft-)deleted.
Consumed by the deletion-cascade worker, which drops the document's Qdrant chunks
and, when `purge_object` is true, hard-deletes the raw object from the S3 object store.

- ARCHIVE: `purge_object = false` — purge chunks only (the raw object stays, so the
  archive is reversible).
- DELETE: `purge_object = true` — purge chunks AND the stored raw object.

```json
{
  "document_id": "uuid",
  "workspace_id": "uuid",
  "object_key": "string|null (object-store key of the raw upload)",
  "collection": "raggie_chunks_d1024",
  "purge_object": false
}
```

## `raggie.chat.completed`
Emitted by the Go edge after a full chat stream (P3). Consumed by the
auto-evaluator (P6).

```json
{ "message_id": "uuid", "conversation_id": "uuid", "workspace_id": "uuid" }
```

Consumer groups: `ingestion-workers`, `eval-workers`. Delivery is at-least-once;
consumers must be idempotent (deterministic point ids for ingestion;
`message_id` dedup for evaluation).
