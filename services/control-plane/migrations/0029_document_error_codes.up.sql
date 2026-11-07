-- SPDX-License-Identifier: Apache-2.0
-- Stable failure codes for documents (contracts/document_errors.md). The
-- ingestion worker stores a code and its params next to the English
-- error_message, so the web can show the reason in the viewer's language.
-- Nullable: rows that failed before this migration keep only error_message.
ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS error_code TEXT,
    ADD COLUMN IF NOT EXISTS error_params JSONB;
