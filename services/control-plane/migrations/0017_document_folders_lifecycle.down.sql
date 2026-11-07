-- SPDX-License-Identifier: Apache-2.0
-- Reverse 0017_document_folders_lifecycle. Drops the lifecycle columns + the
-- folder tree, and narrows the status CHECK back to its original four values.
-- Any rows still in 'ARCHIVED' would block the narrowed CHECK, so reset them to
-- 'SUCCESS' first (archive is reversible; this is the closest live state).

UPDATE documents SET status = 'SUCCESS' WHERE status = 'ARCHIVED';

ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_status_check;
ALTER TABLE documents ADD CONSTRAINT documents_status_check
    CHECK (status IN ('PENDING', 'PROCESSING', 'SUCCESS', 'FAILED'));

DROP INDEX IF EXISTS idx_documents_folder;
ALTER TABLE documents
    DROP COLUMN IF EXISTS folder_id,
    DROP COLUMN IF EXISTS archived_at,
    DROP COLUMN IF EXISTS deleted_at;

DROP TABLE IF EXISTS document_folders;
