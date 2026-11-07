-- SPDX-License-Identifier: Apache-2.0
-- Document Drive (folders) + document lifecycle (archive / soft-delete).
--
-- Adds a per-workspace folder tree (document_folders, self-referential) so the
-- admin Drive can organize uploads into nested folders, and three lifecycle
-- columns on documents:
--   folder_id    — which folder a doc lives in (NULL = workspace root).
--   archived_at  — set on ARCHIVE; the doc keeps its raw object but its Qdrant
--                  chunks are purged out-of-band (document.deleted purge_object=false)
--                  so it stops surfacing in retrieval while staying reversible.
--   deleted_at   — set on (soft) DELETE; the cascade then hard-deletes the Qdrant
--                  chunks AND the MinIO object (document.deleted purge_object=true).
-- A new status value 'ARCHIVED' is allowed so the existing status CHECK still holds.
--
-- All additive + idempotent (CREATE TABLE/INDEX IF NOT EXISTS, ADD COLUMN IF NOT
-- EXISTS, CHECK widened in place) so re-runs and a left-applied rollback are safe.
-- New columns are nullable, so existing rows backfill to folder_id/archived_at/
-- deleted_at = NULL (root, live) in place — no data migration needed.

-- Folder tree ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS document_folders (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id     UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    parent_folder_id UUID REFERENCES document_folders(id) ON DELETE CASCADE,
    name             TEXT NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_document_folders_workspace
    ON document_folders(workspace_id);
CREATE INDEX IF NOT EXISTS idx_document_folders_parent
    ON document_folders(parent_folder_id);
-- One folder name per (workspace, parent), case-insensitive. NULL parent (root)
-- is collapsed to the all-zero UUID so root siblings are de-duplicated too (a
-- plain UNIQUE would treat every NULL parent as distinct).
CREATE UNIQUE INDEX IF NOT EXISTS uq_document_folders_ws_parent_name
    ON document_folders (
        workspace_id,
        COALESCE(parent_folder_id, '00000000-0000-0000-0000-000000000000'::uuid),
        lower(name)
    );

-- updated_at maintenance (reuses the shared set_updated_at trigger fn).
DROP TRIGGER IF EXISTS trg_document_folders_updated ON document_folders;
CREATE TRIGGER trg_document_folders_updated BEFORE UPDATE ON document_folders
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Document lifecycle columns ------------------------------------------------
ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS folder_id   UUID REFERENCES document_folders(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS deleted_at  TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_documents_folder ON documents(folder_id);

-- Allow status = 'ARCHIVED'. Widen the existing CHECK in place (drop + re-add);
-- the constraint name is the default Postgres-generated documents_status_check.
ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_status_check;
ALTER TABLE documents ADD CONSTRAINT documents_status_check
    CHECK (status IN ('PENDING', 'PROCESSING', 'SUCCESS', 'FAILED', 'ARCHIVED'));
