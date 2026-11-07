-- SPDX-License-Identifier: Apache-2.0
-- Persist the server-resolved provider alongside the canonical model id. This
-- supports incident response, cost attribution and local-vs-managed audit.
ALTER TABLE messages ADD COLUMN IF NOT EXISTS model_provider TEXT;

CREATE INDEX IF NOT EXISTS idx_messages_model_provider_audit
    ON messages(model_provider, model_used, created_at DESC)
    WHERE sender = 'BOT' AND model_provider IS NOT NULL;
