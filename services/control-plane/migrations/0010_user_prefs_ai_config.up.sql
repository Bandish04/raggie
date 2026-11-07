-- SPDX-License-Identifier: Apache-2.0
-- Per-user chat preferences + admin-managed AI/model config.
--
-- (A) users.answer_style / preferred_chat_model: each user tunes their own chat
--     persona (answer style) and may pin a preferred model from the allowed set.
--     answer_style is constrained to a small known set; new rows / existing rows
--     default to 'balanced'. preferred_chat_model is nullable (no pin).
-- (B) system_settings.chat_default_model / chat_allowed_models: SUPER_ADMIN
--     curates which model ids the chat picker offers and the platform default.
--     Provider endpoints + keys deliberately stay in the edge's environment,
--     never here (KVKK / on-prem).
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS answer_style         TEXT NOT NULL DEFAULT 'balanced',
    ADD COLUMN IF NOT EXISTS preferred_chat_model TEXT;

-- Guard the allowed answer styles at the DB layer too (API also validates).
-- Backfill any unexpected pre-existing value to 'balanced' before constraining.
UPDATE users
    SET answer_style = 'balanced'
    WHERE answer_style NOT IN ('corporate', 'short', 'instructive', 'balanced');

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'users_answer_style_check'
    ) THEN
        ALTER TABLE users
            ADD CONSTRAINT users_answer_style_check
            CHECK (answer_style IN ('corporate', 'short', 'instructive', 'balanced'));
    END IF;
END$$;

ALTER TABLE system_settings
    ADD COLUMN IF NOT EXISTS chat_default_model  TEXT,
    ADD COLUMN IF NOT EXISTS chat_allowed_models JSONB NOT NULL DEFAULT '[]'::jsonb;
