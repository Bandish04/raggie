-- SPDX-License-Identifier: Apache-2.0

DROP INDEX IF EXISTS idx_documents_integration;
ALTER TABLE documents
    DROP COLUMN IF EXISTS source_ref,
    DROP COLUMN IF EXISTS integration_id,
    DROP COLUMN IF EXISTS provider;
DROP TABLE IF EXISTS integration_sync_state;
DROP TABLE IF EXISTS integrations;
