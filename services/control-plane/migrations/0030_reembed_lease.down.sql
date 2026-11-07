-- SPDX-License-Identifier: Apache-2.0
ALTER TABLE system_settings
    DROP COLUMN IF EXISTS reembed_lease_expires_at,
    DROP COLUMN IF EXISTS reembed_lease_owner;
