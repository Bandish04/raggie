-- SPDX-License-Identifier: Apache-2.0
-- Server-side authentication sessions.
--
-- Access and refresh JWTs carry the opaque session id (sid). Both the control
-- plane and edge check this table, so logout/deactivation revokes tokens
-- immediately instead of waiting for JWT expiry.
CREATE TABLE IF NOT EXISTS auth_sessions (
    id                 UUID PRIMARY KEY,
    user_id            UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    refresh_token_hash TEXT NOT NULL,
    expires_at         TIMESTAMPTZ NOT NULL,
    revoked_at         TIMESTAMPTZ,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_auth_sessions_refresh_hash
    ON auth_sessions(refresh_token_hash);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_user_active
    ON auth_sessions(user_id, expires_at)
    WHERE revoked_at IS NULL;

DROP TRIGGER IF EXISTS trg_auth_sessions_updated ON auth_sessions;
CREATE TRIGGER trg_auth_sessions_updated BEFORE UPDATE ON auth_sessions
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
