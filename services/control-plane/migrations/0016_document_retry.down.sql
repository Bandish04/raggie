-- SPDX-License-Identifier: Apache-2.0
-- Reverse 0016_document_retry: drop the retry sweep index, then the columns.

DROP INDEX IF EXISTS idx_documents_retry;

ALTER TABLE documents
    DROP COLUMN IF EXISTS retry_count,
    DROP COLUMN IF EXISTS last_retry_at,
    DROP COLUMN IF EXISTS max_retries;
