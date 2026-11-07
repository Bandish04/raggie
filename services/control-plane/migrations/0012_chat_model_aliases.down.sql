-- SPDX-License-Identifier: Apache-2.0
-- Reverse 0012: drop the admin-managed chat model display aliases column.
ALTER TABLE system_settings
    DROP COLUMN IF EXISTS chat_model_aliases;
