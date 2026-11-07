-- SPDX-License-Identifier: Apache-2.0
-- Auto-retry bookkeeping for failed document ingestion.
--
-- The ingestion worker is stateless: on an error it marks the document FAILED and
-- acks (no infinite Redis redelivery). The RETRY STATE — how many times we've
-- already re-armed a doc and when we last did so — lives here in Postgres so a
-- separate sweep (in the scheduler worker) can re-enqueue FAILED docs with
-- exponential backoff, capped at max_retries to stop permanent failures (corrupt
-- files) from looping forever. The event contract is unchanged; retry_count never
-- travels in the document.uploaded payload.
--
-- All additive + idempotent (ADD COLUMN IF NOT EXISTS / IF NOT EXISTS index) so
-- re-runs and a left-applied rollback are safe. New columns are non-null with
-- defaults, so existing rows backfill to retry_count=0 / max_retries=3 in place.

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS retry_count   INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS last_retry_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS max_retries   INT NOT NULL DEFAULT 3;

-- The sweep scans only FAILED docs ordered by last_retry_at (NULLS FIRST). A
-- partial index keyed on last_retry_at and confined to status='FAILED' keeps the
-- working set tiny (FAILED is rare) and the periodic scan cheap.
CREATE INDEX IF NOT EXISTS idx_documents_retry
    ON documents (last_retry_at) WHERE status = 'FAILED';
