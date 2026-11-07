-- SPDX-License-Identifier: Apache-2.0
-- SSO + SCIM. Users may now originate from an external IdP (no local
-- password) and be (de)provisioned / (de)activated by a SCIM client.
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS auth_provider TEXT    NOT NULL DEFAULT 'local',
    ADD COLUMN IF NOT EXISTS external_id   TEXT;

-- SCIM externalId is unique per IdP; enforce uniqueness where present.
CREATE UNIQUE INDEX IF NOT EXISTS uq_users_external_id
    ON users(external_id) WHERE external_id IS NOT NULL;
