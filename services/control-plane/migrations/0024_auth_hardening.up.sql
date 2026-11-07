-- SPDX-License-Identifier: Apache-2.0
-- Auth hardening.
--
-- 1. users.is_platform_admin — SUPER_ADMIN is now org-scoped; platform-wide
--    operations (create/list orgs, global settings, operator MCP credentials,
--    platform re-index) require this flag. The edge reads the same column.
--    Backfill: the earliest-created SUPER_ADMIN (the bootstrap user) keeps
--    platform authority, only when no platform admin exists yet (idempotent).
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_platform_admin BOOLEAN NOT NULL DEFAULT FALSE;

UPDATE users SET is_platform_admin = TRUE
 WHERE id = (
        SELECT id FROM users
         WHERE role = 'SUPER_ADMIN'
         ORDER BY created_at, id
         LIMIT 1
       )
   AND NOT EXISTS (SELECT 1 FROM users WHERE is_platform_admin);

-- 2. One-time setup token for POST /onboarding/bootstrap. Only the sha256 hash
--    is stored; the plaintext is logged once at first boot and cleared on use.
ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS setup_token_hash TEXT;

-- 3. External identities (OIDC/SAML). SSO users are matched on the stable
--    (issuer, subject) pair, never on a mutable/unverified email alone.
CREATE TABLE IF NOT EXISTS user_identities (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    issuer        TEXT NOT NULL,
    subject       TEXT NOT NULL,
    email         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_user_identities_issuer_subject UNIQUE (issuer, subject)
);
CREATE INDEX IF NOT EXISTS idx_user_identities_user ON user_identities(user_id);

-- 4. Integration config was double-encoded (json.dumps before the asyncpg jsonb
--    codec, same defect 0022 fixed for ai config), so connect/list failed with a
--    500 and the edge saw a JSON string. Unwrap any stored string scalars.
UPDATE integrations
   SET config = (config #>> '{}')::jsonb
 WHERE jsonb_typeof(config) = 'string';

-- 5. Same double-encoding defect in audit_log.metadata (AuditRepo.record).
--    Only unwrap strings that hold a serialized object/array.
UPDATE audit_log
   SET metadata = (metadata #>> '{}')::jsonb
 WHERE jsonb_typeof(metadata) = 'string'
   AND left(ltrim(metadata #>> '{}'), 1) IN ('{', '[');

-- 6. Refresh-token reuse grace window: the outgoing token's hash and when it
--    was rotated, so a duplicate refresh from a second web replica (immediate
--    predecessor, within REFRESH_REUSE_GRACE_SECONDS) is not treated as theft.
ALTER TABLE auth_sessions
    ADD COLUMN IF NOT EXISTS previous_refresh_token_hash TEXT,
    ADD COLUMN IF NOT EXISTS rotated_at TIMESTAMPTZ;

-- 7. message_feedback.user_id was NOT NULL (part of the primary key) while its
--    users FK is ON DELETE SET NULL, so deleting any user who left feedback —
--    or their org — failed. Feedback is aggregate analytics: keep the rows and
--    anonymize them (user_id NULL) on user deletion. A surrogate key replaces
--    the composite PK; a unique index keeps one vote per (message, user) and
--    still backs the edge's ON CONFLICT (message_id, user_id) upsert.
ALTER TABLE message_feedback
    ADD COLUMN IF NOT EXISTS id UUID NOT NULL DEFAULT gen_random_uuid();
CREATE UNIQUE INDEX IF NOT EXISTS uq_message_feedback_message_user
    ON message_feedback(message_id, user_id);
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'message_feedback'::regclass AND contype = 'p'
           AND pg_get_constraintdef(oid) ILIKE '%user_id%'
    ) THEN
        ALTER TABLE message_feedback DROP CONSTRAINT message_feedback_pkey;
        ALTER TABLE message_feedback ADD CONSTRAINT message_feedback_pkey PRIMARY KEY (id);
    END IF;
END $$;
ALTER TABLE message_feedback ALTER COLUMN user_id DROP NOT NULL;
