-- SPDX-License-Identifier: Apache-2.0

DROP INDEX IF EXISTS idx_messages_model_provider_audit;
ALTER TABLE messages DROP COLUMN IF EXISTS model_provider;
