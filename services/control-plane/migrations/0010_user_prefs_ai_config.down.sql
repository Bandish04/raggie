-- SPDX-License-Identifier: Apache-2.0
-- Reverse 0010: drop per-user chat preferences + admin AI/model config columns.
ALTER TABLE system_settings
    DROP COLUMN IF EXISTS chat_allowed_models,
    DROP COLUMN IF EXISTS chat_default_model;

ALTER TABLE users
    DROP CONSTRAINT IF EXISTS users_answer_style_check;

ALTER TABLE users
    DROP COLUMN IF EXISTS preferred_chat_model,
    DROP COLUMN IF EXISTS answer_style;
