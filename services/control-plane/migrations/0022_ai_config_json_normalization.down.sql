-- SPDX-License-Identifier: Apache-2.0

ALTER TABLE system_settings
    DROP CONSTRAINT IF EXISTS system_settings_chat_allowed_models_shape;
ALTER TABLE system_settings
    DROP CONSTRAINT IF EXISTS system_settings_chat_model_aliases_shape;
