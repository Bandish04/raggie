-- SPDX-License-Identifier: Apache-2.0
-- Managed org directory: Departments (with an assignable lead/owner) + Locations
-- (offices), plus a team head. Turns the previously free-text users.department /
-- users.location into managed, selectable entities — while KEEPING those TEXT
-- columns populated (write-through) because the Go edge reads them verbatim to
-- build the chat persona. All additive + idempotent (IF NOT EXISTS) so re-runs
-- and a left-applied rollback are safe.

-- Departments ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS departments (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id        UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    owner_user_id UUID REFERENCES users(id) ON DELETE SET NULL,  -- lead; display-only, no RBAC
    parent_department_id UUID REFERENCES departments(id) ON DELETE SET NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_departments_org ON departments(org_id);
-- One department name per org (case-insensitive) so the select has no dupes.
CREATE UNIQUE INDEX IF NOT EXISTS uq_departments_org_name
    ON departments(org_id, lower(name));

-- Locations (offices) -------------------------------------------------------
CREATE TABLE IF NOT EXISTS locations (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id     UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    city       TEXT,
    country    TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_locations_org ON locations(org_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_locations_org_name
    ON locations(org_id, lower(name));

-- updated_at maintenance (reuses the shared set_updated_at trigger fn).
DROP TRIGGER IF EXISTS trg_departments_updated ON departments;
CREATE TRIGGER trg_departments_updated BEFORE UPDATE ON departments
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
DROP TRIGGER IF EXISTS trg_locations_updated ON locations;
CREATE TRIGGER trg_locations_updated BEFORE UPDATE ON locations
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- FK links on users + invites (nullable; the TEXT columns stay as the
-- denormalized value the edge reads + a fallback for un-migrated rows).
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS department_id UUID REFERENCES departments(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS location_id   UUID REFERENCES locations(id)   ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_users_department_id ON users(department_id);
CREATE INDEX IF NOT EXISTS idx_users_location_id   ON users(location_id);

ALTER TABLE invites
    ADD COLUMN IF NOT EXISTS department_id UUID REFERENCES departments(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS location_id   UUID REFERENCES locations(id)   ON DELETE SET NULL;

-- Team head (display-only lead of a team; complements team_members).
ALTER TABLE teams
    ADD COLUMN IF NOT EXISTS head_user_id  UUID REFERENCES users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS display_order INT NOT NULL DEFAULT 0;

-- Backfill managed rows from existing free-text values, then link users.
-- trim + collapse so "  Sales " and "Sales" don't create two departments.
INSERT INTO departments (org_id, name)
SELECT DISTINCT u.org_id, btrim(u.department)
FROM users u
WHERE u.org_id IS NOT NULL
  AND u.department IS NOT NULL AND btrim(u.department) <> ''
ON CONFLICT (org_id, lower(name)) DO NOTHING;

INSERT INTO locations (org_id, name)
SELECT DISTINCT u.org_id, btrim(u.location)
FROM users u
WHERE u.org_id IS NOT NULL
  AND u.location IS NOT NULL AND btrim(u.location) <> ''
ON CONFLICT (org_id, lower(name)) DO NOTHING;

UPDATE users u
SET department_id = d.id
FROM departments d
WHERE u.department_id IS NULL
  AND u.org_id = d.org_id
  AND u.department IS NOT NULL
  AND lower(btrim(u.department)) = lower(d.name);

UPDATE users u
SET location_id = l.id
FROM locations l
WHERE u.location_id IS NULL
  AND u.org_id = l.org_id
  AND u.location IS NOT NULL
  AND lower(btrim(u.location)) = lower(l.name);
