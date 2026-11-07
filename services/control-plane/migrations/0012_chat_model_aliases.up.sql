-- SPDX-License-Identifier: Apache-2.0
-- Admin-managed display aliases for chat models.
--
-- system_settings.chat_model_aliases maps a real model id (the value sent to the
-- LLM, e.g. "gpt-oss-120b") to a friendly name shown to users (e.g. "Raggie Pro").
-- SUPER_ADMIN curates this map alongside chat_default_model / chat_allowed_models
-- (0010); any logged-in user reads it via GET /api/v1/models to label the picker.
-- Additive + idempotent (IF NOT EXISTS); new + existing rows default to '{}'.
ALTER TABLE system_settings
    ADD COLUMN IF NOT EXISTS chat_model_aliases JSONB NOT NULL DEFAULT '{}'::jsonb;
