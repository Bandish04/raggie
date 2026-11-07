-- SPDX-License-Identifier: Apache-2.0
-- Raggie initial schema (PostgreSQL 17).
-- Single DDL source of truth, owned by the control plane.
-- Core product tables plus the multi-tenant hierarchy
-- (Organization -> Team -> nested sub-teams -> Workspace), per-org LLM secrets,
-- invites, and an audit log.
--
-- UUID PKs default to gen_random_uuid() (core since PG13). All timestamps are
-- TIMESTAMPTZ. updated_at columns are maintained by the set_updated_at trigger.

-- updated_at trigger function ------------------------------------------------
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Global settings / license --------------------------------------------------
-- llmaas_* here are the SYSTEM DEFAULT, used when an org has no override.
CREATE TABLE system_settings (
    id          TEXT PRIMARY KEY DEFAULT 'current',
    llmaas_api_key_ref TEXT,                 -- reference to a secret, never plaintext
    llmaas_base_url    TEXT DEFAULT 'https://api.llmaas.ai/v1',
    license_key TEXT,
    is_onboarded BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT system_settings_singleton CHECK (id = 'current')
);
CREATE TRIGGER trg_system_settings_updated BEFORE UPDATE ON system_settings
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Organizations (tenant root) ------------------------------------------------
CREATE TABLE organizations (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    llmaas_base_url     TEXT,                -- NULL -> fall back to system default
    llmaas_api_key_ref  TEXT,               -- reference to secret manager / k8s Secret
    embedding_dim       INT,                -- per-org default embedding dimension
    monthly_token_quota BIGINT,             -- per-tenant fairness/billing quota
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TRIGGER trg_organizations_updated BEFORE UPDATE ON organizations
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Users (org-scoped) ---------------------------------------------------------
-- org_id NULL => platform-level SUPER_ADMIN (the initial setup account).
CREATE TABLE users (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id        UUID REFERENCES organizations(id) ON DELETE CASCADE,
    email         TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'STAFF'
                  CHECK (role IN ('SUPER_ADMIN', 'WORKSPACE_ADMIN', 'STAFF')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_users_org_id ON users(org_id);
CREATE TRIGGER trg_users_updated BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Teams: recursive hierarchy via adjacency + closure table -------------------
CREATE TABLE teams (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id         UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    parent_team_id UUID REFERENCES teams(id) ON DELETE CASCADE,  -- NULL = top-level
    name           TEXT NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_teams_org_id ON teams(org_id);
CREATE INDEX idx_teams_parent ON teams(parent_team_id);

-- ancestor/descendant pairs incl. self (depth 0); enables one-query ancestor
-- lookups for effective-access resolution.
CREATE TABLE team_closure (
    ancestor_id   UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    descendant_id UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    depth         INT NOT NULL,
    PRIMARY KEY (ancestor_id, descendant_id)
);
CREATE INDEX idx_team_closure_descendant ON team_closure(descendant_id);

CREATE TABLE team_members (
    team_id UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role    TEXT NOT NULL DEFAULT 'STAFF'
            CHECK (role IN ('SUPER_ADMIN', 'WORKSPACE_ADMIN', 'STAFF')),
    PRIMARY KEY (team_id, user_id)
);
CREATE INDEX idx_team_members_user ON team_members(user_id);

-- Workspaces (org/team scope, per-workspace embedding dim + CORS) ------------
CREATE TABLE workspaces (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id               UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    team_id              UUID REFERENCES teams(id) ON DELETE SET NULL,
    name                 TEXT NOT NULL,
    type                 TEXT NOT NULL CHECK (type IN ('INTERNAL', 'EXTERNAL')),
    system_prompt        TEXT NOT NULL DEFAULT '',
    temperature          REAL NOT NULL DEFAULT 0.3,
    widget_primary_color TEXT NOT NULL DEFAULT '#3498db',
    embedding_dim        INT,                       -- defaults from org/system
    cors_allowed_origins JSONB NOT NULL DEFAULT '[]'::jsonb,  -- validated, no '*'
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_workspaces_org_id ON workspaces(org_id);
CREATE INDEX idx_workspaces_team_id ON workspaces(team_id);
CREATE TRIGGER trg_workspaces_updated BEFORE UPDATE ON workspaces
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE workspace_members (
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role         TEXT NOT NULL DEFAULT 'STAFF'
                 CHECK (role IN ('SUPER_ADMIN', 'WORKSPACE_ADMIN', 'STAFF')),
    PRIMARY KEY (workspace_id, user_id)
);
CREATE INDEX idx_workspace_members_user ON workspace_members(user_id);

-- Documents ------------------------------------------------------------------
CREATE TABLE documents (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id          UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    filename              TEXT NOT NULL,
    file_size             BIGINT NOT NULL,
    status                TEXT NOT NULL DEFAULT 'PENDING'
                          CHECK (status IN ('PENDING', 'PROCESSING', 'SUCCESS', 'FAILED')),
    qdrant_collection_name TEXT NOT NULL,
    object_key            TEXT,              -- MinIO key for the raw upload
    error_message         TEXT,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_documents_workspace ON documents(workspace_id);
CREATE INDEX idx_documents_status ON documents(status);
CREATE TRIGGER trg_documents_updated BEFORE UPDATE ON documents
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Conversations --------------------------------------------------------------
-- user_id NULL for anonymous EXTERNAL widget sessions (session_token set).
CREATE TABLE conversations (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id     UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    user_id          UUID REFERENCES users(id) ON DELETE SET NULL,
    session_token    TEXT,
    evaluation_score REAL NOT NULL DEFAULT 1.0,
    is_flagged       BOOLEAN NOT NULL DEFAULT FALSE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_conversations_workspace ON conversations(workspace_id);
CREATE INDEX idx_conversations_flagged ON conversations(workspace_id) WHERE is_flagged;

-- Messages (+ partial flag for aborted streams) ------------------------------
CREATE TABLE messages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    sender          TEXT NOT NULL CHECK (sender IN ('USER', 'BOT', 'SYSTEM')),
    content         TEXT NOT NULL,
    used_tokens     INT NOT NULL DEFAULT 0,
    sources_json    JSONB,             -- [{ "doc": str, "text": str, "score": float }]
    idempotency_key TEXT,              -- dedups retried chat requests
    partial         BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_messages_conversation ON messages(conversation_id);
CREATE UNIQUE INDEX uq_messages_idempotency ON messages(idempotency_key)
    WHERE idempotency_key IS NOT NULL;

-- Invites: token-based onboarding with a one-time copy-link ------------------
CREATE TABLE invites (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id       UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    email        TEXT NOT NULL,
    role         TEXT NOT NULL DEFAULT 'STAFF'
                 CHECK (role IN ('SUPER_ADMIN', 'WORKSPACE_ADMIN', 'STAFF')),
    team_id      UUID REFERENCES teams(id) ON DELETE CASCADE,
    workspace_id UUID REFERENCES workspaces(id) ON DELETE CASCADE,
    token_hash   TEXT UNIQUE NOT NULL,       -- sha256 of the opaque invite token
    expires_at   TIMESTAMPTZ NOT NULL,
    accepted_at  TIMESTAMPTZ,
    created_by   UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_invites_org ON invites(org_id);

-- Audit log ------------------------------------------------------------------
CREATE TABLE audit_log (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id        UUID REFERENCES organizations(id) ON DELETE SET NULL,
    actor_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    action        TEXT NOT NULL,
    target        TEXT,
    metadata      JSONB,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_audit_org_created ON audit_log(org_id, created_at DESC);
