// SPDX-License-Identifier: Apache-2.0

// Package vectorstore is the edge's read-side Qdrant client (search only).
package vectorstore

import (
	"fmt"
	"regexp"
)

// CollectionName derives the legacy Qdrant collection for an embedding
// dimension. It is only the fallback for an older embeddings gateway that does
// not name the collection in its /v1/query response; the gateway's value is
// authoritative (contracts/embeddings_gateway.schema.json). Scheme source of
// truth: contracts/qdrant_collection.json (CI checks all sides).
func CollectionName(embeddingDim int) string {
	return fmt.Sprintf("raggie_chunks_d%d", embeddingDim)
}

// collectionPattern is the gateway contract's collection name grammar
// ($defs.collection.pattern): raggie_chunks_d{dim}, optionally suffixed with
// the 8-hex embedding-profile fingerprint.
var collectionPattern = regexp.MustCompile(`^raggie_chunks_d[0-9]+(_[0-9a-f]{8})?$`)

// ValidCollectionName reports whether name is a collection the gateway may
// legitimately return. The name is interpolated into the Qdrant URL path, so
// anything else is refused before a request is built.
func ValidCollectionName(name string) bool {
	return collectionPattern.MatchString(name)
}
