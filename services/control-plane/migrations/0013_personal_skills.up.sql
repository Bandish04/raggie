-- SPDX-License-Identifier: Apache-2.0
-- Personal skills (0013): a user may create/edit/delete their OWN skills,
-- alongside the admin-published org skills. The chat picker shows the UNION
-- (org-published + the caller's personal). Additive + idempotent.
--
--   owner_user_id NULL      → an org/published skill (admin-managed, as before)
--   owner_user_id non-null  → a personal skill owned by that user
--   visibility 'org'        → default keeps EVERY existing row as a published org
--                             skill, so there is zero data migration.
ALTER TABLE skills ADD COLUMN IF NOT EXISTS owner_user_id UUID
    REFERENCES users(id) ON DELETE CASCADE;

ALTER TABLE skills ADD COLUMN IF NOT EXISTS visibility TEXT NOT NULL DEFAULT 'org'
    CHECK (visibility IN ('personal', 'org'));

-- Replace the single org-wide slug uniqueness with two namespaces so the SAME
-- slug (e.g. "ozet") can exist once org-wide AND once per user: org skills are
-- unique on (org_id, slug) only among published rows (owner_user_id IS NULL),
-- and personal skills are unique on (org_id, owner_user_id, slug).
DROP INDEX IF EXISTS uq_skills_org_slug;

CREATE UNIQUE INDEX IF NOT EXISTS uq_skills_org_slug
    ON skills (org_id, slug) WHERE owner_user_id IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_skills_personal_slug
    ON skills (org_id, owner_user_id, slug);

-- The effective chat picker filters by org + owner; index it.
CREATE INDEX IF NOT EXISTS idx_skills_org_owner ON skills (org_id, owner_user_id);
