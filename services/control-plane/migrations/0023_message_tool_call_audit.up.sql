-- SPDX-License-Identifier: Apache-2.0
-- Audit-safe summary of model-requested tool calls for a BOT turn. Raw tool
-- arguments/results are intentionally not stored; the edge writes hashes,
-- latencies, status, and sizes only.
ALTER TABLE messages ADD COLUMN IF NOT EXISTS tool_calls_json JSONB;

CREATE INDEX IF NOT EXISTS idx_messages_tool_calls_audit
    ON messages USING GIN (tool_calls_json)
    WHERE tool_calls_json IS NOT NULL;
