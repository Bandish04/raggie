-- SPDX-License-Identifier: Apache-2.0

DROP INDEX IF EXISTS idx_messages_tool_calls_audit;
ALTER TABLE messages DROP COLUMN IF EXISTS tool_calls_json;
