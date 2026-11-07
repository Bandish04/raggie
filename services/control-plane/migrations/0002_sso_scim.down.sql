-- SPDX-License-Identifier: Apache-2.0

DROP INDEX IF EXISTS uq_users_external_id;
ALTER TABLE users
    DROP COLUMN IF EXISTS external_id,
    DROP COLUMN IF EXISTS auth_provider,
    DROP COLUMN IF EXISTS is_active;
