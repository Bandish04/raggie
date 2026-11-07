-- SPDX-License-Identifier: Apache-2.0
-- Embedding-profile fingerprints (contracts/embeddings_gateway.schema.json).
-- The embeddings gateway identifies its active profile (provider, model, dim,
-- prefixes, provider extras) by an 8-hex fingerprint and names the Qdrant
-- collection after it. system_settings keeps the profile the platform accepted
-- (set at boot by the control plane); every document records the profile it is
-- indexed with, so a model switch is detected instead of silently mixing
-- vector spaces.
ALTER TABLE system_settings
    ADD COLUMN IF NOT EXISTS embedding_fingerprint TEXT,
    ADD COLUMN IF NOT EXISTS embedding_profile JSONB;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS embedding_fingerprint TEXT;

-- Everything in the pre-gateway collection was embedded with the legacy local
-- profile (intfloat/multilingual-e5-large, 1024-d, E5 prefixes), whose
-- fingerprint is 2872ae6a and which keeps that collection name: zero re-embed
-- for existing installs. Rows in other collections stay NULL (unknown profile).
UPDATE documents SET embedding_fingerprint = '2872ae6a'
 WHERE qdrant_collection_name = 'raggie_chunks_d1024' AND embedding_fingerprint IS NULL;

-- The gateway's profile is now the only source of the embedding dimension; the
-- per-org / per-workspace overrides from 0001 are read by nothing.
ALTER TABLE organizations DROP COLUMN IF EXISTS embedding_dim;
ALTER TABLE workspaces DROP COLUMN IF EXISTS embedding_dim;

CREATE INDEX IF NOT EXISTS idx_documents_live_embedding_fingerprint
    ON documents (embedding_fingerprint)
    WHERE deleted_at IS NULL AND archived_at IS NULL;
