-- SPDX-License-Identifier: Apache-2.0

DROP INDEX IF EXISTS idx_documents_live_embedding_fingerprint;
-- Restores the columns (empty: the dropped values were never read).
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS embedding_dim INT;
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS embedding_dim INT;
ALTER TABLE documents DROP COLUMN IF EXISTS embedding_fingerprint;
ALTER TABLE system_settings
    DROP COLUMN IF EXISTS embedding_profile,
    DROP COLUMN IF EXISTS embedding_fingerprint;
