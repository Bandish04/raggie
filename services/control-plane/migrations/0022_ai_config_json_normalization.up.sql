-- SPDX-License-Identifier: Apache-2.0
-- Normalize AI configuration written by control-plane builds that serialized
-- JSON before passing values through asyncpg's JSONB codec. Those builds stored
-- arrays/maps as JSON strings, which made the edge reject every chat request.
UPDATE system_settings
SET chat_allowed_models = (chat_allowed_models #>> '{}')::jsonb
WHERE jsonb_typeof(chat_allowed_models) = 'string';

UPDATE system_settings
SET chat_model_aliases = (chat_model_aliases #>> '{}')::jsonb
WHERE jsonb_typeof(chat_model_aliases) = 'string';

ALTER TABLE system_settings
    DROP CONSTRAINT IF EXISTS system_settings_chat_allowed_models_shape;
ALTER TABLE system_settings
    ADD CONSTRAINT system_settings_chat_allowed_models_shape
    CHECK (jsonb_typeof(chat_allowed_models) = 'array');

ALTER TABLE system_settings
    DROP CONSTRAINT IF EXISTS system_settings_chat_model_aliases_shape;
ALTER TABLE system_settings
    ADD CONSTRAINT system_settings_chat_model_aliases_shape
    CHECK (jsonb_typeof(chat_model_aliases) = 'object');
