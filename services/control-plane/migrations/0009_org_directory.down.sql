-- SPDX-License-Identifier: Apache-2.0
-- Reverse 0009_org_directory. Drops the FK links + managed tables. The original
-- free-text users.department / users.location columns are untouched, so no data
-- is lost on rollback.
ALTER TABLE teams
    DROP COLUMN IF EXISTS head_user_id,
    DROP COLUMN IF EXISTS display_order;

ALTER TABLE invites
    DROP COLUMN IF EXISTS department_id,
    DROP COLUMN IF EXISTS location_id;

ALTER TABLE users
    DROP COLUMN IF EXISTS department_id,
    DROP COLUMN IF EXISTS location_id;

DROP TABLE IF EXISTS locations;
DROP TABLE IF EXISTS departments;
