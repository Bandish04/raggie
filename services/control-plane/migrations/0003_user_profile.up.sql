-- SPDX-License-Identifier: Apache-2.0
-- Raggie rich user profile (LDAP-like) + per-user locale + temp-password flag.
-- Powers chat personalization (who is asking: title, department, manager, tenure)
-- and the Account Settings surface. Invites carry pre-filled profile metadata so
-- an admin can seed an account before the invitee accepts. All additive +
-- idempotent (IF NOT EXISTS) so re-runs are safe; the set_updated_at trigger on
-- users keeps updated_at maintained for the new columns for free.

-- Rich profile columns on users ---------------------------------------------
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS full_name            TEXT,
    ADD COLUMN IF NOT EXISTS job_title            TEXT,
    ADD COLUMN IF NOT EXISTS department           TEXT,
    ADD COLUMN IF NOT EXISTS manager_user_id      UUID REFERENCES users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS hire_date            DATE,            -- tenure computed at read time
    ADD COLUMN IF NOT EXISTS phone                TEXT,
    ADD COLUMN IF NOT EXISTS location             TEXT,
    ADD COLUMN IF NOT EXISTS timezone             TEXT NOT NULL DEFAULT 'Europe/Istanbul',
    ADD COLUMN IF NOT EXISTS locale               TEXT NOT NULL DEFAULT 'tr'
        CHECK (locale IN ('tr', 'en')),                            -- keep in sync with SUPPORTED_LOCALES
    ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_users_manager    ON users(manager_user_id);
CREATE INDEX IF NOT EXISTS idx_users_department ON users(org_id, department);

-- Invites carry pre-filled profile + revocation -----------------------------
ALTER TABLE invites
    ADD COLUMN IF NOT EXISTS full_name       TEXT,
    ADD COLUMN IF NOT EXISTS job_title       TEXT,
    ADD COLUMN IF NOT EXISTS department      TEXT,
    ADD COLUMN IF NOT EXISTS manager_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS phone           TEXT,
    ADD COLUMN IF NOT EXISTS location        TEXT,
    ADD COLUMN IF NOT EXISTS timezone        TEXT,
    ADD COLUMN IF NOT EXISTS locale          TEXT,
    ADD COLUMN IF NOT EXISTS revoked_at      TIMESTAMPTZ;

-- Fast lookup of still-actionable invites (pending = not accepted, not revoked).
CREATE INDEX IF NOT EXISTS idx_invites_org_pending
    ON invites(org_id) WHERE accepted_at IS NULL AND revoked_at IS NULL;
