-- SPDX-License-Identifier: Apache-2.0
-- Restores the columns (empty), deliberately without the old external default.
ALTER TABLE system_settings
    ADD COLUMN IF NOT EXISTS llmaas_base_url TEXT,
    ADD COLUMN IF NOT EXISTS llmaas_api_key_ref TEXT;
ALTER TABLE organizations
    ADD COLUMN IF NOT EXISTS llmaas_base_url TEXT,
    ADD COLUMN IF NOT EXISTS llmaas_api_key_ref TEXT;
ALTER TABLE users ALTER COLUMN locale SET DEFAULT 'tr';
ALTER TABLE messages DROP COLUMN IF EXISTS interrupted_reason;
-- The widget-origin normalization is not reverted: the normalized form is what
-- the edge matches, and the original spellings are not kept.
