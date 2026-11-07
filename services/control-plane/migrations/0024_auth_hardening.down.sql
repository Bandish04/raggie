-- SPDX-License-Identifier: Apache-2.0
-- Restoring the composite key requires dropping anonymized feedback rows.
DELETE FROM message_feedback WHERE user_id IS NULL;
ALTER TABLE message_feedback DROP CONSTRAINT IF EXISTS message_feedback_pkey;
ALTER TABLE message_feedback ALTER COLUMN user_id SET NOT NULL;
ALTER TABLE message_feedback ADD CONSTRAINT message_feedback_pkey PRIMARY KEY (message_id, user_id);
DROP INDEX IF EXISTS uq_message_feedback_message_user;
ALTER TABLE message_feedback DROP COLUMN IF EXISTS id;
ALTER TABLE auth_sessions
    DROP COLUMN IF EXISTS previous_refresh_token_hash,
    DROP COLUMN IF EXISTS rotated_at;
DROP TABLE IF EXISTS user_identities;
ALTER TABLE system_settings DROP COLUMN IF EXISTS setup_token_hash;
ALTER TABLE users DROP COLUMN IF EXISTS is_platform_admin;
