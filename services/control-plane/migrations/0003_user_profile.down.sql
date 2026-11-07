-- SPDX-License-Identifier: Apache-2.0
-- Reverse 0003_user_profile.

DROP INDEX IF EXISTS idx_invites_org_pending;
ALTER TABLE invites
    DROP COLUMN IF EXISTS revoked_at,
    DROP COLUMN IF EXISTS locale,
    DROP COLUMN IF EXISTS timezone,
    DROP COLUMN IF EXISTS location,
    DROP COLUMN IF EXISTS phone,
    DROP COLUMN IF EXISTS manager_user_id,
    DROP COLUMN IF EXISTS department,
    DROP COLUMN IF EXISTS job_title,
    DROP COLUMN IF EXISTS full_name;

DROP INDEX IF EXISTS idx_users_department;
DROP INDEX IF EXISTS idx_users_manager;
ALTER TABLE users
    DROP COLUMN IF EXISTS must_change_password,
    DROP COLUMN IF EXISTS locale,
    DROP COLUMN IF EXISTS timezone,
    DROP COLUMN IF EXISTS location,
    DROP COLUMN IF EXISTS phone,
    DROP COLUMN IF EXISTS hire_date,
    DROP COLUMN IF EXISTS manager_user_id,
    DROP COLUMN IF EXISTS department,
    DROP COLUMN IF EXISTS job_title,
    DROP COLUMN IF EXISTS full_name;
