-- SPDX-License-Identifier: Apache-2.0
-- Reverse 0013: restore the single org-wide slug uniqueness, drop the namespace
-- indexes and the two new columns.
DROP INDEX IF EXISTS idx_skills_org_owner;
DROP INDEX IF EXISTS uq_skills_personal_slug;
DROP INDEX IF EXISTS uq_skills_org_slug;

CREATE UNIQUE INDEX IF NOT EXISTS uq_skills_org_slug ON skills (org_id, slug);

ALTER TABLE skills DROP COLUMN IF EXISTS visibility;
ALTER TABLE skills DROP COLUMN IF EXISTS owner_user_id;
